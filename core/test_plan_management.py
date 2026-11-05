from datetime import timedelta
from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.backoffice_forms import CommercialPlanForm
from core.plan_forms import PlanAdminForm
from subscriptions.models import Plan, PlanEntitlement, PlanVersion, Subscription
from accounts.models import Organization
from gardens.models import GardenModel
from subscriptions.selectors import plan_publication_diagnostics
from subscriptions.selectors import get_current_plan_version


class PlanManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="plan-admin@example.test", password="Strong-pass-2026!", full_name="Admin")
        self.plan = Plan.objects.create(name="Plano Base", code="plano-base", is_active=True, is_public=True)
        self.version = PlanVersion.objects.create(plan=self.plan, version=1, price_cents=10000, effective_from=timezone.now() - timedelta(days=1))

    def test_removed_textarea_items_are_really_deleted(self):
        PlanEntitlement.objects.create(plan_version=self.version, benefit_type="item-1", name="Mantido")
        PlanEntitlement.objects.create(plan_version=self.version, benefit_type="item-2", name="Removido")
        form = CommercialPlanForm({"name": self.plan.name, "code": self.plan.code, "monthly_price": "100.00", "included_items": "Mantido", "is_active": "on", "is_public": "on"}, instance=self.plan)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(list(self.version.entitlements.values_list("name", flat=True)), ["Mantido"])

    def test_future_version_does_not_replace_current_early(self):
        future = timezone.now() + timedelta(days=10)
        self.version.retired_at = future
        self.version.save()
        PlanVersion.objects.create(plan=self.plan, version=2, price_cents=12000, effective_from=future)
        self.assertEqual(get_current_plan_version(self.plan), self.version)

    def test_management_is_admin_only(self):
        user = User.objects.create_user(email="customer-plan@example.test", password="Strong-pass-2026!")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("ops-plan-management")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("ops-plan-management")).status_code, 200)

    def test_admin_create_and_edit_forms_render(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("ops-plan-create")).status_code, 200)
        response = self.client.get(reverse("ops-plan-edit", args=[self.plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Serviços incluídos")

    def _plan_payload(self, **changes):
        data = {
            "name": "Plano Visual", "commercial_title": "Horta em casa", "short_copy": "Plano integrado",
            "description": "Descrição", "code": "plano-visual", "display_order": "1",
            "monthly_price": "149.90", "installation_fee": "250.00", "is_active": "on", "is_public": "on",
            "benefits-TOTAL_FORMS": "1", "benefits-INITIAL_FORMS": "0", "benefits-MIN_NUM_FORMS": "0", "benefits-MAX_NUM_FORMS": "1000",
            "benefits-0-name": "Suporte técnico", "benefits-0-icon": "bi-headset", "benefits-0-description": "Atendimento",
            "benefits-0-quantity": "1", "benefits-0-unit": "visitas/mês", "benefits-0-display_order": "0", "benefits-0-is_included": "on",
        }
        data.update(changes)
        return data

    def test_create_plan_persists_currency_and_benefit(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-plan-create"), self._plan_payload())
        self.assertEqual(response.status_code, 302)
        plan = Plan.objects.get(code="plano-visual")
        self.assertEqual(plan.installation_fee_cents, 25000)
        self.assertEqual(plan.versions.get().price_cents, 14990)
        self.assertEqual(plan.versions.get().entitlements.get().name, "Suporte técnico")

    def test_image_upload_replace_and_remove(self):
        def uploaded(color):
            output = BytesIO(); Image.new("RGB", (32, 32), color).save(output, "PNG")
            return SimpleUploadedFile("horta.png", output.getvalue(), content_type="image/png")
        form = PlanAdminForm({**self._plan_payload(), "benefits-TOTAL_FORMS": "0"}, {"image": uploaded("green")}, instance=self.plan)
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(); form.save_image(plan); first = bytes(plan.image_data)
        form = PlanAdminForm({**self._plan_payload(), "code": self.plan.code, "name": self.plan.name, "remove_image": ""}, {"image": uploaded("blue")}, instance=plan)
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(); form.save_image(plan)
        self.assertNotEqual(first, bytes(plan.image_data))
        form = PlanAdminForm({**self._plan_payload(), "code": self.plan.code, "name": self.plan.name, "remove_image": "on"}, instance=plan)
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(); form.save_image(plan)
        self.assertIsNone(plan.image_data)

    def test_new_price_version_preserves_existing_contract(self):
        organization = Organization.objects.create(name="Cliente", slug="cliente-plan-version")
        subscription = Subscription.objects.create(organization=organization, plan_version=self.version, contracted_price_cents=10000, status=Subscription.Status.ACTIVE, current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30))
        form = PlanAdminForm({**self._plan_payload(), "code": self.plan.code, "name": self.plan.name, "monthly_price": "199.90"}, instance=self.plan)
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(); new_version = form.create_version(plan, self.version)
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan_version_id, self.version.pk)
        self.assertEqual(subscription.contracted_price_cents, 10000)
        self.assertEqual(new_version.price_cents, 19990)

    def test_comparison_and_navigation_are_dynamic(self):
        PlanEntitlement.objects.create(plan_version=self.version, benefit_type="camera", name="Câmera", is_included=True)
        response = self.client.get(reverse("plans"))
        self.assertContains(response, "Câmera")
        self.assertContains(response, 'aria-current="page"')
        for name in ("home", "how-it-works", "crop-catalog", "about", "faq"):
            self.assertContains(self.client.get(reverse(name)), 'aria-current="page"')

    def test_public_card_selects_the_exact_version(self):
        response = self.client.get(reverse("checkout-plan", args=[self.version.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["checkout"]["plan"], str(self.version.pk))

    def test_public_plan_and_detail_use_the_same_data(self):
        PlanEntitlement.objects.create(plan_version=self.version, benefit_type="item-1", name="Visita mensal", is_included=True)
        for url in (reverse("plans"), reverse("plan-detail", args=[self.plan.code])):
            response = self.client.get(url)
            self.assertContains(response, "Plano Base")
            self.assertContains(response, "Visita mensal")

    def test_numeric_code_opens_the_correct_eligible_plan(self):
        self.plan.code = "02"; self.plan.save(update_fields=["code"])
        response = self.client.get(reverse("plan-detail", args=["02"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plano Base")
        self.assertEqual(self.client.get(reverse("plan-detail", args=["99"])).status_code, 404)

    def test_publication_diagnostics_explain_missing_version_and_model(self):
        self.version.retired_at = timezone.now() - timedelta(minutes=1); self.version.save()
        diagnostic = plan_publication_diagnostics(self.plan)
        self.assertIn("Sem versão de preço vigente", diagnostic["issues"])
        self.assertIn("Associe um modelo de horta", diagnostic["issues"])
        self.assertFalse(diagnostic["is_published"])

    def test_garden_model_values_are_reflected_publicly(self):
        model = GardenModel.objects.create(name="Premium", code="premium-model", capacity=12, reservoir_liters=20, height_cm=260)
        self.plan.garden_model = model; self.plan.save()
        response = self.client.get(reverse("plans"))
        self.assertContains(response, "12 mudas")
        self.assertContains(response, "20")
        self.assertContains(response, "260")

    def test_only_one_plan_remains_featured(self):
        self.plan.is_featured = True; self.plan.save()
        other = Plan.objects.create(name="Outro", code="outro", is_active=True, is_public=True)
        PlanVersion.objects.create(plan=other, version=1, price_cents=20000, effective_from=timezone.now())
        form = PlanAdminForm({**self._plan_payload(), "name": other.name, "code": other.code, "is_featured": "on"}, instance=other)
        self.assertTrue(form.is_valid(), form.errors)
        form.save(); self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_featured)
        self.assertTrue(other.is_featured)

    def test_deactivation_keeps_versions(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("ops-plan-toggle", args=[self.plan.pk]))
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_active)
        self.assertTrue(PlanVersion.objects.filter(pk=self.version.pk).exists())
