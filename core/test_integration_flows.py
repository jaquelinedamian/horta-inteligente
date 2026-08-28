from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from crops.models import Crop, Cultivar
from subscriptions.models import Plan, PlanVersion, Subscription


class IntegratedProductFlowsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin-flow@example.test", password="Strong-pass-2026!", full_name="Admin Fluxo")

    def test_admin_plan_creation_publishes_same_version_everywhere(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-create", args=["plans"]), {
            "name": "Essencial Integrado", "code": "essencial-integrado", "description": "Plano de teste integrado",
            "monthly_price": "149.90", "included_items": "3 módulos\nMonitoramento remoto", "is_public": "on", "is_active": "on",
        })
        self.assertEqual(response.status_code, 302)
        plan = Plan.objects.get(code="essencial-integrado")
        version = plan.versions.get()
        self.assertEqual(version.price_cents, 14990)
        self.assertEqual(version.entitlements.count(), 2)
        for url in (reverse("plans"), reverse("plan-detail", args=[plan.code]), reverse("checkout", args=[1])):
            response = self.client.get(url)
            self.assertContains(response, "Essencial Integrado")

    def test_available_crop_is_shared_by_catalog_and_checkout(self):
        plan = Plan.objects.create(name="Plano", code="plano", is_active=True, is_public=True)
        PlanVersion.objects.create(plan=plan, version=1, price_cents=10000, effective_from=timezone.now())
        crop = Crop.objects.create(common_name="Manjericão Integrado", code="manjericao-integrado", is_available=True)
        Cultivar.objects.create(crop=crop, name="Genovese", is_active=True)
        self.assertContains(self.client.get(reverse("crop-catalog")), "Manjericão Integrado")
        self.assertContains(self.client.get(reverse("checkout", args=[1])), "Plano")
        session = self.client.session
        session["checkout"] = {"plan": str(plan.versions.get().pk)}
        session.save()
        checkout = self.client.get(reverse("checkout", args=[2]))
        self.assertContains(checkout, "Manjericão Integrado")
        self.assertNotContains(checkout, "Genovese")

    def test_admin_subscription_is_visible_to_linked_customer(self):
        user = User.objects.create_user(email="customer-flow@example.test", password="Strong-pass-2026!", full_name="Cliente Fluxo")
        organization = Organization.objects.create(name="Cliente Fluxo", slug="cliente-fluxo")
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        plan = Plan.objects.create(name="Plano Administrativo", code="plano-administrativo", is_active=True, is_public=True)
        version = PlanVersion.objects.create(plan=plan, version=1, price_cents=19990, effective_from=timezone.now())
        Subscription.objects.create(organization=organization, plan_version=version, status=Subscription.Status.ACTIVE, current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30), contracted_price_cents=18990)
        self.client.force_login(user)
        response = self.client.get(reverse("customer-section", args=["subscription"]))
        self.assertContains(response, "Plano Administrativo")
