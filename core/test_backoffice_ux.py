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
        for area, title in (("comercial", "Clientes"), ("configuracoes", "Planos e assinaturas"), ("cultivo", "Cultivo"), ("hortas", "Hortas"), ("iot", "IoT"), ("operacao", "Operação"), ("estoque", "Estoque"), ("administracao", "Administração")):
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
        cases = (("devices", "iot"), ("plans", "configuracoes"), ("inventory", "estoque"))
        for section, area in cases:
            response = self.client.get(reverse("ops-collection", args=[section]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["backoffice_current_area"], area)
            self.assertContains(response, "Configurações")
            self.assertNotContains(response, "Organizações</a>")
            self.assertNotContains(response, "Cupons</a>")
            self.assertNotContains(response, "Pagamentos</a>")

    def test_current_sidebar_item_is_accessible_and_active(self):
        response = self.client.get(reverse("ops-collection", args=["devices"]))
        self.assertContains(response, "Modelos de horta")
        self.assertContains(response, "Planos/Assinaturas")
        self.assertContains(response, "Dispositivos")
        self.assertContains(response, "Configurações técnicas")
        self.assertNotContains(response, 'id="backoffice-area-selector"')

    def test_admin_dashboard_exposes_only_mvp_navigation(self):
        response = self.client.get(reverse("ops-dashboard"))
        for label in ("Dashboard", "Clientes", "Hortas", "Culturas", "Visitas", "Equipe", "Estoque", "Configurações"):
            self.assertContains(response, label)
        for hidden in ("Organizações</a>", "Cupons</a>", "Pagamentos</a>"):
            self.assertNotContains(response, hidden)
        for setting in ("Modelos de horta", "Planos/Assinaturas", "Dispositivos", "Configurações técnicas"):
            self.assertContains(response, setting)

    def test_legacy_commercial_area_does_not_expose_old_links(self):
        response = self.client.get(reverse("ops-area", args=["comercial"]))
        self.assertContains(response, "Clientes")
        self.assertEqual([card["section"] for card in response.context["cards"]], ["clients"])
        for hidden in ("Organizações</a>", "Cupons</a>", "Pagamentos</a>"):
            self.assertNotContains(response, hidden)
