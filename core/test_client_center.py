import secrets

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization, User
from subscriptions.models import Payment, Subscription


class ClientCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", password=secrets.token_urlsafe(18), verbosity=0)
        cls.admin = User.objects.get(email="admin@hortaviva.local")
        cls.customer = User.objects.get(email="cliente@hortaviva.local")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_admin_sees_summary_and_all_local_navigation(self):
        response = self.client.get(reverse("ops-client-detail", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Central do cliente")
        for label in ("Resumo", "Dados", "Assinatura", "Horta", "Módulos", "Cultivos", "Dispositivos", "Visitas", "Pagamentos", "Suporte"):
            self.assertContains(response, label)

    def test_edit_client_renders_real_fields(self):
        response = self.client.get(reverse("ops-client-edit", args=[self.customer.pk]))
        self.assertContains(response, 'name="full_name"')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="street"')
        self.assertContains(response, 'name="property_type"')

    def test_contextual_payment_only_accepts_customer_subscription(self):
        customer_org = self.customer.memberships.get(role=Membership.Role.OWNER).organization
        other_org = Organization.objects.exclude(pk=customer_org.pk).filter(subscriptions__isnull=False).first()
        if not other_org:
            self.skipTest("Seed has no second organization with subscription")
        foreign_subscription = other_org.subscriptions.first()
        response = self.client.post(reverse("ops-client-related-create", args=[self.customer.pk, "payments"]), {
            "subscription": foreign_subscription.pk, "amount_cents": 1000, "currency": "BRL", "status": Payment.Status.PENDING, "due_at": "2026-09-10T10:00",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Payment.objects.filter(subscription=foreign_subscription, amount_cents=1000).exists())

    def test_contextual_subscription_forces_customer_organization(self):
        response = self.client.get(reverse("ops-client-related-create", args=[self.customer.pk, "subscriptions"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="organization"')
        customer_org = self.customer.memberships.get(role=Membership.Role.OWNER).organization
        self.assertEqual(response.context["form"].fields["organization"].initial, customer_org)
