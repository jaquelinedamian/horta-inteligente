import secrets

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from operations.models import InventoryCategory


class BackofficeUXTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = secrets.token_urlsafe(18)
        call_command("seed_demo", password=cls.password, verbosity=0)
        cls.admin = User.objects.get(email="admin@hortaviva.local")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_area_pages_are_available_in_portuguese(self):
        for area, title in (("comercial", "Comercial"), ("cultivo", "Cultivo"), ("hortas", "Hortas"), ("iot", "IoT"), ("operacao", "Operação"), ("estoque", "Estoque"), ("administracao", "Administração")):
            response = self.client.get(reverse("ops-area", args=[area]))
            self.assertEqual(response.status_code, 200, area)
            self.assertContains(response, title)

    def test_inventory_form_is_portuguese_and_hides_legacy_category(self):
        response = self.client.get(reverse("ops-create", args=["inventory"]))
        self.assertContains(response, "Categoria de estoque")
        self.assertContains(response, "Nova categoria")
        self.assertContains(response, "Novo fornecedor")
        self.assertContains(response, "Selecione uma opção")
        self.assertNotContains(response, 'name="category"')

    def test_category_created_in_quick_flow_appears_in_item_form(self):
        response = self.client.post(reverse("ops-create", args=["inventory-categories"]), {"name": "Adubos", "description": "Nutrição sólida", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        category = InventoryCategory.objects.get(name="Adubos")
        response = self.client.get(reverse("ops-create", args=["inventory"]))
        self.assertContains(response, f'value="{category.pk}"')
        self.assertContains(response, "Adubos")

    def test_customer_and_technician_cannot_access_area(self):
        for email in ("cliente@hortaviva.local", "tecnico@hortaviva.local"):
            self.client.force_login(User.objects.get(email=email))
            self.assertEqual(self.client.get(reverse("ops-area", args=["estoque"])).status_code, 403)

    def test_sidebar_detects_area_from_direct_resource_url(self):
        cases = (("devices", "iot", "Dispositivos", "Planos"), ("plans", "comercial", "Planos", "Telemetria"), ("inventory", "estoque", "Itens", "Culturas"))
        for section, area, visible, hidden in cases:
            response = self.client.get(reverse("ops-collection", args=[section]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["backoffice_current_area"], area)
            self.assertContains(response, visible)
            self.assertNotContains(response, f'>{hidden}</a>')

    def test_current_sidebar_item_is_accessible_and_active(self):
        response = self.client.get(reverse("ops-collection", args=["devices"]))
        self.assertContains(response, 'data-section="devices" class="active" aria-current="page"', html=False)
        self.assertContains(response, 'id="backoffice-area-selector"')
