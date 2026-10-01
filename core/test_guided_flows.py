from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from devices.models import Device


class GuidedBackofficeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="guided-admin@example.test", password="Strong-pass-2026!", full_name="Admin")
        self.client.force_login(self.admin)

    def test_dashboard_prioritizes_business_actions(self):
        response = self.client.get(reverse("ops-dashboard"))
        self.assertContains(response, "O que você quer fazer?")
        self.assertContains(response, "Novo plano de assinatura")
        self.assertContains(response, "Nova cultura")
        self.assertContains(response, "Configurações")

    def test_primary_creation_routes_use_reusable_stepper(self):
        for section in ("plans", "crops", "gardens", "modules", "employees", "inventory", "devices", "visits", "orders"):
            with self.subTest(section=section):
                response = self.client.get(reverse("ops-create", args=[section]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'data-guided-wizard', html=False)
                self.assertContains(response, "Por que precisamos disso?")
                self.assertContains(response, "Salvar rascunho")

    def test_customer_onboarding_is_guided(self):
        response = self.client.get(reverse("ops-client-create"))
        self.assertContains(response, "Novo cliente")
        self.assertContains(response, "Assinatura")
        self.assertContains(response, 'data-wizard-stepper', html=False)

    def test_device_flow_exposes_kind_choices_for_dynamic_summary(self):
        response = self.client.get(reverse("ops-create", args=["devices"]))
        self.assertContains(response, "Tipo do dispositivo")
        self.assertContains(response, Device.Kind.CONTROLLER.label)
        self.assertContains(response, Device.Kind.CAMERA.label)
        self.assertContains(response, 'name="kind"', html=False)
        self.assertContains(response, 'data-wizard-summary', html=False)
