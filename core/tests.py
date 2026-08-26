import secrets

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Organization, User
from gardens.models import GardenModule
from operations.models import Visit


class PortalSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", password=secrets.token_urlsafe(18), verbosity=0)

    def test_public_navigation_renders(self):
        for name in ("home", "how-it-works", "plans", "crop-catalog", "about", "faq", "contact", "login", "signup"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_customer_pages_are_tenant_scoped(self):
        self.client.force_login(User.objects.get(email="cliente@hortaviva.local"))
        for url in (reverse("customer-dashboard"), reverse("customer-history"), reverse("customer-support"), reverse("customer-profile"), reverse("customer-section", args=["garden"]), reverse("customer-section", args=["crops"]), reverse("customer-section", args=["alerts"]), reverse("customer-section", args=["visits"]), reverse("customer-section", args=["subscription"]), reverse("customer-section", args=["payments"])):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        other = Organization.objects.create(name="Outro cliente", slug="outro")
        module = GardenModule.objects.filter(organization=other).first()
        if module:
            self.assertEqual(self.client.get(reverse("module-detail", args=[module.id])).status_code, 404)

    def test_technician_and_admin_areas_render(self):
        technician = User.objects.get(email="tecnico@hortaviva.local")
        self.client.force_login(technician)
        self.assertEqual(self.client.get(reverse("tech-dashboard")).status_code, 200)
        visit = Visit.objects.get(technician=technician)
        self.assertEqual(self.client.get(reverse("visit-detail", args=[visit.id])).status_code, 200)
        self.client.force_login(User.objects.get(email="admin@hortaviva.local"))
        self.assertEqual(self.client.get(reverse("ops-dashboard")).status_code, 200)
        for section in ("clients", "subscriptions", "plans", "crops", "gardens", "modules", "qrcodes", "devices", "telemetry", "alerts", "employees", "agenda", "orders", "inventory", "finance", "reports", "settings"):
            self.assertEqual(self.client.get(reverse("ops-collection", args=[section])).status_code, 200, section)

    def test_customer_cannot_open_operations_portal(self):
        self.client.force_login(User.objects.get(email="cliente@hortaviva.local"))
        self.assertEqual(self.client.get(reverse("ops-dashboard")).status_code, 403)
