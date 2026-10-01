import secrets

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization, User
from crops.models import Crop, Cultivar, PlantingCycle
from devices.models import Channel, Device, DeviceModel
from gardens.models import Garden, GardenModel, GardenModule, ModuleInstallation, ModuleType
from gardens.services import install_module, move_module
from django.core.exceptions import ValidationError
from django.utils import timezone
from subscriptions.models import Payment, Subscription


class ClientCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", password=secrets.token_urlsafe(18), verbosity=0)
        cls.admin = User.objects.get(email="admin@hortaviva.local")
        cls.customer = User.objects.get(email="cliente@hortaviva.local")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_admin_sees_only_simplified_client_navigation(self):
        response = self.client.get(reverse("ops-client-detail", args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Central do cliente")
        for label in ("Resumo", "Dados", "Assinatura", "Horta", "Visitas", "Suporte"):
            self.assertContains(response, label)
        for section in ("modules", "cycles", "devices", "payments"):
            self.assertNotContains(response, f"?aba={section}")

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

    def _module_payload(self, serial, placement="stock", garden=None):
        return {"module_type": ModuleType.objects.first().pk, "serial_number": serial, "name": f"Módulo {serial}", "placement": placement, "garden": garden.pk if garden else "", "installation_position": "Superior", "installation_date": "2026-08-28T12:00"}

    def _customer_org_garden(self):
        organization = self.customer.memberships.get(role=Membership.Role.OWNER).organization
        garden = Garden.objects.filter(organization=organization).first()
        if not garden:
            garden = Garden.objects.create(organization=organization, name="Horta principal", code="principal", status=Garden.Status.INSTALLED)
        return organization, garden

    def test_admin_creates_installed_module_and_customer_sees_it(self):
        organization, garden = self._customer_org_garden()
        response = self.client.post(reverse("ops-client-related-create", args=[self.customer.pk, "modules"]), self._module_payload("CENTER-INST-1", "install", garden))
        self.assertEqual(response.status_code, 302)
        module = GardenModule.objects.get(serial_number="CENTER-INST-1")
        self.assertEqual(module.status, GardenModule.Status.INSTALLED)
        self.assertTrue(ModuleInstallation.objects.filter(module=module, garden=garden, removed_at__isnull=True).exists())
        self.client.force_login(self.customer)
        response = self.client.get(reverse("customer-section", args=["garden"]))
        self.assertContains(response, module.name)
        self.assertContains(response, "Sem cultivo")

    def test_stock_module_is_admin_only_not_installed_for_customer(self):
        organization, garden = self._customer_org_garden()
        self.client.post(reverse("ops-client-related-create", args=[self.customer.pk, "modules"]), self._module_payload("CENTER-STOCK-1"))
        module = GardenModule.objects.get(serial_number="CENTER-STOCK-1")
        self.assertEqual(module.status, GardenModule.Status.STOCK)
        self.assertFalse(module.installations.filter(removed_at__isnull=True).exists())
        self.client.force_login(self.customer)
        self.assertNotContains(self.client.get(reverse("customer-section", args=["garden"])), module.name)

    def test_legacy_module_tab_falls_back_without_exposing_module_structure(self):
        organization, garden = self._customer_org_garden()
        ModuleInstallation.objects.filter(module__organization=organization, removed_at__isnull=True).update(removed_at=timezone.now())
        module = GardenModule.objects.create(organization=organization, module_type=ModuleType.objects.first(), serial_number="BROKEN-INST-1", name="Módulo inconsistente", status=GardenModule.Status.INSTALLED)
        response = self.client.get(f"{reverse('ops-client-detail', args=[self.customer.pk])}?aba=modules")
        self.assertEqual(response.context["active_tab"], "resumo")
        self.assertNotContains(response, "Instalação incompleta")
        self.assertNotContains(response, "Nenhuma horta vinculada")
        self.assertNotContains(response, module.name)

    def test_cross_organization_install_is_blocked(self):
        organization, garden = self._customer_org_garden()
        other = Organization.objects.exclude(pk=organization.pk).first()
        foreign_garden = Garden.objects.filter(organization=other).first() or Garden.objects.create(organization=other, name="Horta externa", code="externa")
        module = GardenModule.objects.create(organization=organization, module_type=ModuleType.objects.first(), serial_number="CROSS-ORG-1", name="Módulo protegido")
        with self.assertRaises(ValidationError):
            install_module(module, foreign_garden)
        self.assertFalse(module.installations.exists())

    def test_installed_module_with_active_cycle_shows_crop(self):
        organization, garden = self._customer_org_garden()
        module = GardenModule.objects.create(organization=organization, module_type=ModuleType.objects.first(), serial_number="CROP-MOD-1", name="Módulo com cultivo")
        install_module(module, garden)
        cultivar = Cultivar.objects.filter(is_active=True).select_related("crop").first()
        PlantingCycle.objects.create(organization=organization, garden=garden, module=module, crop=cultivar.crop, cultivar=cultivar, status=PlantingCycle.Status.ACTIVE, planted_at=timezone.now())
        self.client.force_login(self.customer)
        response = self.client.get(reverse("customer-section", args=["garden"]))
        self.assertContains(response, module.name)
        self.assertContains(response, cultivar.crop.common_name)

    def test_install_does_not_silently_replace_active_installation(self):
        organization, garden = self._customer_org_garden()
        other_garden = Garden.objects.create(organization=organization, name="Segunda horta", code="segunda")
        module = GardenModule.objects.create(organization=organization, module_type=ModuleType.objects.first(), serial_number="MOVE-MOD-1", name="Módulo móvel")
        first = install_module(module, garden)
        with self.assertRaises(ValidationError):
            install_module(module, other_garden)
        second = move_module(module, other_garden)
        first.refresh_from_db()
        self.assertIsNotNone(first.removed_at)
        self.assertIsNone(second.removed_at)
        self.assertEqual(second.garden, other_garden)


class LegacyGardenClientCenterTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="legacy-admin@example.test",
            password="test",
            full_name="Admin",
            employee_role=User.EmployeeRole.ADMIN,
        )
        self.customer = User.objects.create_user(
            email="legacy-customer@example.test", password="test", full_name="Cliente legado"
        )
        self.organization = Organization.objects.create(name="Cliente legado", slug="cliente-legado")
        Membership.objects.create(
            user=self.customer, organization=self.organization, role=Membership.Role.OWNER
        )
        self.device_model = DeviceModel.objects.create(name="Hardware legado", code="hardware-legado")
        self.client.force_login(self.admin)

    def _garden(self, code="legada", **kwargs):
        return Garden.objects.create(
            organization=self.organization, name=f"Horta {code}", code=code, **kwargs
        )

    def _response(self):
        return self.client.get(
            f"{reverse('ops-client-detail', args=[self.customer.pk])}?aba=gardens"
        )

    def _device(self, garden, kind, serial):
        return Device.objects.create(
            organization=self.organization,
            garden=garden,
            model=self.device_model,
            serial_number=serial,
            name=serial,
            kind=kind,
        )

    def test_minimal_legacy_garden_returns_200(self):
        self._garden()
        response = self._response()
        self.assertEqual(response.status_code, 200)
        for text in (
            "Não definido", "Não configurado", "Sem comunicação",
            "Nenhuma fotografia", "Nenhuma cultura contratada",
            "Nenhuma cultura plantada", "Não agendada",
        ):
            self.assertContains(response, text)

    def test_garden_without_garden_model_returns_200(self):
        self._garden(garden_model=None)
        self.assertEqual(self._response().status_code, 200)

    def test_garden_without_subscription_returns_200(self):
        self._garden(subscription=None)
        self.assertEqual(self._response().status_code, 200)

    def test_garden_without_devices_returns_200(self):
        self._garden()
        response = self._response()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não configurado", count=2)

    def test_garden_without_planting_cycle_returns_200(self):
        self._garden()
        response = self._response()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhuma cultura plantada")

    def test_garden_with_only_esp8266_returns_200(self):
        garden = self._garden()
        self._device(garden, Device.Kind.CONTROLLER, "ESP8266-ONLY")
        response = self._response()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Controlador ESP8266")
        self.assertContains(response, "Câmera ESP32-CAM")

    def test_garden_with_only_esp32_cam_returns_200(self):
        garden = self._garden()
        self._device(garden, Device.Kind.CAMERA, "ESP32-CAM-ONLY")
        response = self._response()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Controlador ESP8266")
        self.assertContains(response, "Câmera ESP32-CAM")

    def test_garden_with_legacy_config_returns_200(self):
        self._garden(automation_overrides=["irrigation", "camera"])
        self.assertEqual(self._response().status_code, 200)

    def test_complete_garden_returns_200(self):
        garden_model = GardenModel.objects.create(
            name="Completa", code="completa", capacity=4, photos_per_day=6
        )
        garden = self._garden(
            garden_model=garden_model,
            automation_overrides={
                "irrigation": {"frequency_count": 2, "frequency_period": "dia", "pump_duration_seconds": 15},
                "lighting": {"hours_per_day": 8},
                "camera": {"photos_per_day": 6},
            },
        )
        controller = self._device(garden, Device.Kind.CONTROLLER, "ESP8266-COMPLETE")
        self._device(garden, Device.Kind.CAMERA, "ESP32-CAM-COMPLETE")
        self.assertTrue(controller.channels.filter(metric="pump_state").exists())
        Channel.objects.create(
            device=controller, key="light", name="Luz", kind=Channel.Kind.ACTUATOR,
            metric="light_state", value_type=Channel.ValueType.BOOLEAN,
        )
        response = self._response()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Irrigar agora")
        self.assertContains(response, "Ligar luz")
