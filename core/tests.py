import secrets
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from crops.models import Cultivar
from gardens.models import GardenModule, ModuleType
from operations.models import Visit
from subscriptions.models import CheckoutRequest, Payment, Plan, PlanVersion, Subscription


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
        self.cultivars = list(Cultivar.objects.filter(crop__is_available=True)[:4])

    def post_step(self, step, data):
        return self.client.post(reverse("checkout", args=[step]), data)

    def test_checkout_rejects_skipped_steps_and_plan_limit(self):
        self.assertRedirects(self.client.get(reverse("checkout", args=[7])), reverse("checkout", args=[1]))
        self.post_step(1, {"plan": self.plan.id})
        response = self.post_step(2, {"cultures": [item.id for item in self.cultivars]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "permite até 3 culturas")

    def test_complete_checkout_is_consistent_and_idempotent(self):
        self.assertRedirects(self.post_step(1, {"plan": self.plan.id}), reverse("checkout", args=[2]))
        self.assertRedirects(self.post_step(2, {"cultures": [self.cultivars[0].id]}), reverse("checkout", args=[3]))
        address = {"street": "Rua Teste", "number": "10", "city": "São Paulo", "state": "SP", "postal_code": "01001-000"}
        self.assertRedirects(self.post_step(3, address), reverse("checkout", args=[4]))
        self.assertRedirects(self.post_step(4, {"sunlight": "medium", "wifi_available": "on"}), reverse("checkout", args=[5]))
        future = (timezone.now() + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
        self.assertRedirects(self.post_step(5, {"scheduled_for": future}), reverse("checkout", args=[6]))
        self.assertRedirects(self.post_step(6, {}), reverse("checkout", args=[7]))
        self.assertEqual(self.client.post(reverse("checkout-complete")).status_code, 200)
        self.assertEqual(Membership.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Subscription.objects.filter(organization__memberships__user=self.user).count(), 1)
        self.assertEqual(Payment.objects.filter(subscription__organization__memberships__user=self.user).count(), 1)
        self.assertEqual(CheckoutRequest.objects.filter(user=self.user).count(), 1)
        self.client.post(reverse("checkout-complete"))
        self.assertEqual(Subscription.objects.filter(organization__memberships__user=self.user).count(), 1)
        self.assertEqual(Payment.objects.filter(subscription__organization__memberships__user=self.user).count(), 1)

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
