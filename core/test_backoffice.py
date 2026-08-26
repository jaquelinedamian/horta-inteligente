import secrets
from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from crops.models import Crop
from devices.models import Channel, Device, DeviceModel
from gardens.models import Garden, GardenModule, ModuleType
from operations.models import Visit, WorkOrder
from subscriptions.models import Plan, PlanVersion, Subscription


class BackofficeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = secrets.token_urlsafe(18)
        call_command("seed_demo", password=cls.password, verbosity=0)
        cls.admin = User.objects.get(email="admin@hortaviva.local")

    def setUp(self):
        self.client.force_login(self.admin)

    def assert_created(self, section, data):
        response = self.client.post(reverse("ops-create", args=[section]), data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        return response

    def test_admin_can_create_customer_with_organization_and_optional_subscription(self):
        plan = PlanVersion.objects.first()
        response = self.client.post(reverse("ops-client-create"), {
            "full_name": "Cliente Administrativo", "email": "cliente.admin@example.test", "phone": "11999999999",
            "password": "Uma-senha-forte-2026!", "user_is_active": "on", "organization_name": "Cliente Administrativo",
            "organization_slug": "cliente-administrativo", "tax_id": "", "street": "Rua Verde", "number": "10",
            "city": "São Paulo", "state": "SP", "postal_code": "01000-000", "plan_version": plan.pk,
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="cliente.admin@example.test")
        organization = user.memberships.get(role=Membership.Role.OWNER).organization
        self.assertTrue(Subscription.objects.filter(organization=organization).exists())

    def test_admin_creates_core_operational_chain(self):
        self.assert_created("organizations", {"name": "Organização CRUD", "slug": "organizacao-crud", "kind": "company", "tax_id": "", "is_active": "on"})
        organization = Organization.objects.get(slug="organizacao-crud")
        self.assert_created("plans", {"name": "Plano CRUD", "code": "plano-crud", "description": "Plano criado pela interface", "is_active": "on"})
        plan = Plan.objects.get(code="plano-crud")
        now = timezone.now()
        self.assert_created("plan-versions", {"plan": plan.pk, "version": 1, "price_cents": 19990, "currency": "BRL", "billing_interval_months": 1, "effective_from": now.strftime("%Y-%m-%dT%H:%M"), "retired_at": ""})
        version = PlanVersion.objects.get(plan=plan)
        self.assert_created("subscriptions", {"organization": organization.pk, "plan_version": version.pk, "status": "active", "current_period_start": now.strftime("%Y-%m-%dT%H:%M"), "current_period_end": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M"), "canceled_at": "", "provider": "manual", "provider_reference": "CRUD-1"})
        self.assert_created("crops", {"common_name": "Cultura CRUD", "scientific_name": "Species test", "code": "cultura-crud", "description": "Teste", "difficulty": "Fácil", "light_requirement": "6 horas", "uses": "Teste", "is_available": "on"})
        self.assert_created("gardens", {"organization": organization.pk, "name": "Horta CRUD", "code": "horta-crud", "address": "", "timezone": "America/Sao_Paulo", "is_active": "on"})
        garden = Garden.objects.get(code="horta-crud")
        module_type = ModuleType.objects.first()
        self.assert_created("modules", {"organization": organization.pk, "module_type": module_type.pk, "serial_number": "CRUD-MOD-001", "name": "Módulo CRUD", "status": "stock"})
        module = GardenModule.objects.get(serial_number="CRUD-MOD-001")
        device_model = DeviceModel.objects.first()
        self.assert_created("devices", {"organization": organization.pk, "model": device_model.pk, "module": module.pk, "serial_number": "CRUD-DEV-001", "name": "Dispositivo CRUD", "status": "provisioning", "firmware_version": "1.0", "metadata": "{}"})
        device = Device.objects.get(serial_number="CRUD-DEV-001")
        self.assert_created("channels", {"device": device.pk, "key": "temperature", "name": "Temperatura", "kind": "sensor", "metric": "air_temperature", "unit": "°C", "value_type": "decimal", "pin": "I2C", "configuration": "{}", "is_enabled": "on"})
        self.assert_created("orders", {"organization": organization.pk, "garden": garden.pk, "module": module.pk, "device": device.pk, "maintenance_plan": "", "kind": "installation", "status": "open", "title": "Instalar horta CRUD", "description": "", "priority": 2, "scheduled_for": (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"), "completed_at": ""})
        order = WorkOrder.objects.get(title="Instalar horta CRUD")
        technician = User.objects.get(email="tecnico@hortaviva.local")
        self.assert_created("visits", {"organization": organization.pk, "garden": garden.pk, "work_order": order.pk, "technician": technician.pk, "visit_type": "Instalação", "scheduled_start": (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"), "scheduled_end": (now + timedelta(days=2, hours=1)).strftime("%Y-%m-%dT%H:%M"), "status": "scheduled", "notes": ""})
        self.assertTrue(Channel.objects.filter(device=device).exists())
        self.assertTrue(Visit.objects.filter(work_order=order).exists())

    def test_admin_can_edit_critical_entity(self):
        crop = Crop.objects.first()
        response = self.client.post(reverse("ops-edit", args=["crops", crop.pk]), {"common_name": "Nome atualizado", "scientific_name": crop.scientific_name, "code": crop.code, "description": crop.description, "difficulty": crop.difficulty, "light_requirement": crop.light_requirement, "uses": crop.uses, "is_available": "on"})
        self.assertEqual(response.status_code, 302)
        crop.refresh_from_db()
        self.assertEqual(crop.common_name, "Nome atualizado")

    def test_permissions_for_backoffice(self):
        self.client.force_login(User.objects.get(email="cliente@hortaviva.local"))
        self.assertEqual(self.client.get(reverse("ops-dashboard")).status_code, 403)
        self.client.force_login(User.objects.get(email="tecnico@hortaviva.local"))
        self.assertEqual(self.client.get(reverse("ops-dashboard")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("ops-dashboard")).status_code, 200)

    def test_device_credential_is_shown_once_and_qr_is_safe(self):
        device = Device.objects.first()
        response = self.client.post(reverse("ops-credential-issue", args=[device.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "não poderá ser consultado novamente")
        module = GardenModule.objects.first()
        response = self.client.get(reverse("ops-module-qr", args=[module.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"hortaviva:module:{module.pk}")
        download = self.client.get(reverse("ops-module-qr", args=[module.pk]) + "?download=1")
        self.assertEqual(download["Content-Type"], "image/png")
