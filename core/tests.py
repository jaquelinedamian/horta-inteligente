import secrets
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from crops.models import Crop, Cultivar
from gardens.models import Garden, GardenModel, GardenModule, ModuleType
from operations.models import ChecklistExecution, Visit
from subscriptions.models import CheckoutRequest, Payment, Plan, PlanVersion, Subscription
from .backoffice_forms import VisitForm


class DemoDataTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo_password = secrets.token_urlsafe(18)
        call_command("seed_demo", password=cls.demo_password, verbosity=0)


class PublicAndAuthenticationTests(DemoDataTestCase):
    def test_public_navigation_renders(self):
        for name in ("home", "how-it-works", "plans", "crop-catalog", "about", "faq", "contact", "login", "signup"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_login_routes_customer_and_logout_requires_post(self):
        response = self.client.post(reverse("login"), {"username": "cliente@hortaviva.local", "password": self.demo_password}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("customer-dashboard"))
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_user_without_membership_sees_pending_account(self):
        user = User.objects.create_user(email="novo@example.test", full_name="Novo Cliente", password="safe-test-password")
        self.client.force_login(user)
        response = self.client.get(reverse("post-login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ainda não encontramos")

    def test_customer_area_requires_authentication(self):
        response = self.client.get(reverse("customer-dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('customer-dashboard')}")


class CheckoutTests(DemoDataTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="checkout@example.test", full_name="Cliente Checkout", password="safe-test-password")
        self.client.force_login(self.user)
        self.plan = PlanVersion.objects.get(plan__code="essencial")
        self.garden_model = GardenModel.objects.create(name="HortaViva Checkout", code="hv-checkout", capacity=3, photos_per_day=4)
        self.plan.plan.garden_model = self.garden_model
        self.plan.plan.save(update_fields=["garden_model", "updated_at"])
        self.cultivars = list(Cultivar.objects.filter(crop__is_available=True)[:4])
        self.crops = list(Crop.objects.filter(is_available=True)[:4])

    def post_step(self, step, data):
        return self.client.post(reverse("checkout", args=[step]), data)

    def test_checkout_rejects_skipped_steps_and_plan_limit(self):
        self.assertEqual(self.client.get(reverse("checkout", args=[7])).status_code, 404)
        self.post_step(1, {"plan": self.plan.id})
        response = self.post_step(2, {"cultures": [item.id for item in self.crops]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "permite até 3 culturas")

    def test_complete_checkout_is_consistent_and_idempotent(self):
        self.assertRedirects(self.post_step(1, {"plan": self.plan.id}), reverse("checkout", args=[2]))
        self.assertRedirects(self.post_step(2, {"cultures": [self.crops[0].id]}), reverse("checkout", args=[3]))
        address = {"street": "Rua Teste", "number": "10", "city": "São Paulo", "state": "SP", "postal_code": "01001-000"}
        self.assertRedirects(self.post_step(3, address), reverse("checkout", args=[4]))
        self.assertEqual(self.client.post(reverse("checkout-complete")).status_code, 200)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Subscription.objects.filter(organization__memberships__user=self.user).count(), 1)
        self.assertEqual(Payment.objects.filter(subscription__organization__memberships__user=self.user).count(), 0)
        self.assertEqual(CheckoutRequest.objects.filter(user=self.user).count(), 1)
        self.assertEqual(CheckoutRequest.objects.get(user=self.user).selected_crops.count(), 1)
        garden = Garden.objects.get(subscription__organization__memberships__user=self.user)
        subscription = Subscription.objects.get(organization__memberships__user=self.user)
        self.assertEqual(garden.status, Garden.Status.WAITING_INSTALLATION)
        self.assertEqual(garden.garden_model, self.garden_model)
        self.assertEqual(garden.subscription, subscription)
        self.assertEqual(garden.address.postal_code, "01001-000")
        self.assertFalse(garden.devices.exists())
        self.assertFalse(garden.planting_cycles.exists())
        self.client.post(reverse("checkout-complete"))
        self.assertEqual(Subscription.objects.filter(organization__memberships__user=self.user).count(), 1)
        self.assertEqual(Payment.objects.filter(subscription__organization__memberships__user=self.user).count(), 0)
        self.assertEqual(Garden.objects.filter(subscription__organization__memberships__user=self.user).count(), 1)

    def test_checkout_has_friendly_empty_plan_state(self):
        Plan.objects.update(is_active=False)
        response = self.client.get(reverse("checkout", args=[1]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhum plano disponível")


class CustomerPortalTests(DemoDataTestCase):
    def test_customer_pages_render_and_are_tenant_scoped(self):
        self.client.force_login(User.objects.get(email="cliente@hortaviva.local"))
        urls = [reverse("customer-dashboard"), reverse("customer-history"), reverse("customer-support"), reverse("customer-profile")]
        urls += [reverse("customer-section", args=[section]) for section in ("garden", "crops", "alerts", "visits", "subscription", "payments")]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        other = Organization.objects.create(name="Outro cliente", slug="outro-cliente")
        module = GardenModule.objects.create(organization=other, module_type=ModuleType.objects.first(), serial_number="OTHER-001", name="Privado")
        self.assertEqual(self.client.get(reverse("module-detail", args=[module.id])).status_code, 404)

    def test_expected_empty_states_render(self):
        cases = {
            "semassinatura@hortaviva.local": "Finalize sua assinatura",
            "semhorta@hortaviva.local": "horta ainda está sendo preparada",
            "semdispositivo@hortaviva.local": "Dispositivo ainda não conectado",
            "semtelemetria@hortaviva.local": "Aguardando telemetria",
        }
        for email, expected in cases.items():
            with self.subTest(email=email):
                self.client.force_login(User.objects.get(email=email))
                response = self.client.get(reverse("customer-dashboard"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, expected)

    def test_roles_cannot_cross_portals(self):
        self.client.force_login(User.objects.get(email="cliente@hortaviva.local"))
        self.assertEqual(self.client.get(reverse("ops-dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("tech-dashboard")).status_code, 403)
        self.client.force_login(User.objects.get(email="tecnico@hortaviva.local"))
        self.assertEqual(self.client.get(reverse("ops-dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("customer-dashboard")).status_code, 403)

    def test_technician_and_admin_areas_render(self):
        technician = User.objects.get(email="tecnico@hortaviva.local")
        self.client.force_login(technician)
        self.assertEqual(self.client.get(reverse("tech-dashboard")).status_code, 200)
        visit = Visit.objects.filter(technician=technician).first()
        self.assertEqual(self.client.get(reverse("visit-detail", args=[visit.id])).status_code, 200)
        self.client.force_login(User.objects.get(email="admin@hortaviva.local"))
        self.assertEqual(self.client.get(reverse("ops-dashboard")).status_code, 200)
        for section in ("clients", "subscriptions", "plans", "crops", "gardens", "modules", "qrcodes", "devices", "telemetry", "alerts", "employees", "agenda", "orders", "inventory", "finance", "reports", "settings"):
            self.assertEqual(self.client.get(reverse("ops-collection", args=[section])).status_code, 200, section)

    def test_technician_records_installation_test_status(self):
        technician = User.objects.get(email="tecnico@hortaviva.local")
        visit = Visit.objects.filter(technician=technician).first()
        self.client.force_login(technician)
        response = self.client.post(reverse("visit-update", args=[visit.id]), {
            "action": "checklist",
            "all_item": ["Testar sensores", "Testar câmera"],
            "item_status_0": "ok",
            "item_status_1": "failed",
        })
        self.assertEqual(response.status_code, 302)
        checklist = ChecklistExecution.objects.get(visit=visit)
        self.assertEqual(checklist.items[0]["status"], "ok")
        self.assertEqual(checklist.items[1]["status"], "failed")


class VisitOperationalAccessTests(DemoDataTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.get(email="admin@hortaviva.local")
        cls.technician = User.objects.get(email="tecnico@hortaviva.local")
        cls.customer = User.objects.get(email="cliente@hortaviva.local")
        cls.visit = Visit.objects.filter(technician=cls.technician).first()
        cls.other_technician = User.objects.create_user(email="outro.tecnico@example.test", full_name="Outro Técnico")
        Membership.objects.create(
            organization=cls.visit.organization,
            user=cls.other_technician,
            role=Membership.Role.TECHNICIAN,
        )

    def test_admin_can_access_any_visit(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("visit-detail", args=[self.visit.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visualização administrativa")

        collection = self.client.get(reverse("ops-collection", args=["visits"]))
        self.assertContains(collection, reverse("visit-detail", args=[self.visit.id]))
        detail = self.client.get(reverse("ops-detail", args=["visits", self.visit.id]))
        self.assertContains(detail, "Acompanhar operação")

    def test_operational_screen_uses_independent_connectivity_and_new_checklist(self):
        ChecklistExecution.objects.filter(visit=self.visit).delete()
        self.client.force_login(self.admin)
        response = self.client.get(reverse("visit-detail", args=[self.visit.id]))
        self.assertContains(response, "Controlador ESP8266")
        self.assertContains(response, "Câmera ESP32-CAM")
        self.assertContains(response, "Horta-Camera-XXXX")
        self.assertContains(response, "Configurar Wi-Fi do ESP8266")
        self.assertContains(response, "Configurar Wi-Fi da ESP32-CAM")
        self.assertNotContains(response, "Configurar Wi-Fi local")
        self.assertNotContains(response, "repassa as credenciais")
        self.assertNotContains(response, "UART")

        checklist = ChecklistExecution.objects.get(visit=self.visit)
        wifi_items = [item["label"] for item in checklist.items if item["label"].startswith("Configurar Wi-Fi")]
        self.assertEqual(wifi_items, ["Configurar Wi-Fi do ESP8266", "Configurar Wi-Fi da ESP32-CAM"])

    def test_existing_legacy_checklist_is_rendered_without_changes(self):
        legacy_items = [
            {"label": "Identificar horta", "done": True, "status": "ok"},
            {"label": "Configurar Wi-Fi local", "done": False, "status": "failed"},
        ]
        ChecklistExecution.objects.update_or_create(visit=self.visit, defaults={"items": legacy_items})
        self.client.force_login(self.admin)

        response = self.client.get(reverse("visit-detail", args=[self.visit.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configurar Wi-Fi local")
        self.assertEqual(ChecklistExecution.objects.get(visit=self.visit).items, legacy_items)

    def test_admin_sees_warning_for_legacy_non_technician_assignee(self):
        self.visit.technician = self.customer
        self.visit.save(update_fields=["technician"])
        self.client.force_login(self.admin)
        response = self.client.get(reverse("visit-detail", args=[self.visit.id]))
        self.assertContains(response, "Responsável legado inválido")

    def test_only_assigned_technician_can_access_visit(self):
        self.client.force_login(self.technician)
        self.assertEqual(self.client.get(reverse("visit-detail", args=[self.visit.id])).status_code, 200)
        self.client.force_login(self.other_technician)
        self.assertEqual(self.client.get(reverse("visit-detail", args=[self.visit.id])).status_code, 404)

    def test_customer_cannot_access_operational_visit(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("visit-detail", args=[self.visit.id])).status_code, 403)

    def test_visit_form_lists_only_technicians(self):
        form = VisitForm()
        technicians = form.fields["technician"].queryset
        self.assertIn(self.technician, technicians)
        self.assertIn(self.other_technician, technicians)
        self.assertNotIn(self.customer, technicians)

    def test_visit_form_rejects_garden_from_another_organization(self):
        other_organization = Organization.objects.create(name="Outra organização", slug="outra-organizacao-visita")
        other_garden = Garden.objects.create(organization=other_organization, name="Outra horta", code="outra-horta-visita")
        form = VisitForm(data={
            "organization": self.visit.organization_id,
            "garden": other_garden.id,
            "work_order": "",
            "technician": self.technician.id,
            "visit_type": "Vistoria",
            "scheduled_start": (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
            "scheduled_end": (timezone.now() + timedelta(days=1, hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "status": Visit.Status.SCHEDULED,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("garden", form.errors)
