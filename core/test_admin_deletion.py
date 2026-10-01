from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from crops.models import Crop, Cultivar, PlantingCycle
from devices.models import Device, DeviceCredential, DeviceModel, GardenPhoto
from gardens.models import Garden, GardenModule, ModuleType
from operations.models import Visit
from subscriptions.models import Plan, PlanVersion
from core.deletion_services import delete_customer_completely


class AdministrativeDeletionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="delete-admin@example.test", password="test", full_name="Admin",
            employee_role=User.EmployeeRole.ADMIN,
        )
        self.technician = User.objects.create_user(
            email="delete-tech@example.test", password="test", full_name="Técnico",
            employee_role=User.EmployeeRole.TECHNICIAN,
        )
        self.customer = User.objects.create_user(
            email="delete-customer@example.test", password="test", full_name="Cliente",
        )
        self.organization = Organization.objects.create(name="Cliente", slug="delete-cliente")
        Membership.objects.create(user=self.customer, organization=self.organization, role=Membership.Role.OWNER)
        self.garden = Garden.objects.create(organization=self.organization, name="Horta", code="horta")
        self.device_model = DeviceModel.objects.create(name="ESP", code="delete-esp")
        self.client.force_login(self.admin)

    def _device(self, kind=Device.Kind.CONTROLLER):
        return Device.objects.create(
            organization=self.organization, garden=self.garden, model=self.device_model,
            serial_number=f"SERIAL-{kind}", name="Dispositivo", kind=kind,
        )

    def test_admin_can_access_delete_confirmation(self):
        response = self.client.get(reverse("ops-delete", args=["gardens", self.garden.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tem certeza que deseja excluir?")
        self.assertContains(response, "EXCLUIR")

    def test_customer_cannot_use_administrative_delete(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("ops-delete", args=["gardens", self.garden.pk])).status_code, 403)

    def test_technician_cannot_use_administrative_delete(self):
        self.client.force_login(self.technician)
        self.assertEqual(self.client.get(reverse("ops-delete", args=["gardens", self.garden.pk])).status_code, 403)

    def test_get_only_shows_confirmation_and_never_deletes(self):
        response = self.client.get(reverse("ops-delete", args=["gardens", self.garden.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Garden.objects.filter(pk=self.garden.pk).exists())

    def test_csrf_is_required_for_delete_post(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        response = csrf_client.post(
            reverse("ops-delete", args=["gardens", self.garden.pk]),
            {"confirmation": "EXCLUIR", "action": "delete"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Garden.objects.filter(pk=self.garden.pk).exists())

    def test_simple_customer_can_be_deleted(self):
        user = User.objects.create_user(email="simple@example.test", password="test")
        organization = Organization.objects.create(name="Simples", slug="simple-delete")
        Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
        response = self.client.post(reverse("ops-client-delete", args=[user.pk]), {"confirmation": "EXCLUIR"})
        self.assertRedirects(response, reverse("ops-collection", args=["clients"]))
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(Organization.objects.filter(pk=organization.pk).exists())

    def test_customer_with_garden_can_be_deleted_completely(self):
        response = self.client.post(reverse("ops-client-delete", args=[self.customer.pk]), {"confirmation": "EXCLUIR"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Garden.objects.filter(pk=self.garden.pk).exists())
        self.assertFalse(User.objects.filter(pk=self.customer.pk).exists())

    def test_customer_with_device_removes_credentials_and_photos(self):
        device = self._device(Device.Kind.CAMERA)
        credential, _ = DeviceCredential.issue(device)
        photo = GardenPhoto.objects.create(
            garden=self.garden, device=device, captured_at=timezone.now(),
            image_data=b"photo", content_type="image/jpeg", byte_size=5,
        )
        self.client.post(reverse("ops-client-delete", args=[self.customer.pk]), {"confirmation": "EXCLUIR"})
        self.assertFalse(Device.objects.filter(pk=device.pk).exists())
        self.assertFalse(DeviceCredential.objects.filter(pk=credential.pk).exists())
        self.assertFalse(GardenPhoto.objects.filter(pk=photo.pk).exists())

    def test_garden_can_be_deleted_with_linked_data(self):
        device = self._device()
        response = self.client.post(
            reverse("ops-delete", args=["gardens", self.garden.pk]),
            {"confirmation": "EXCLUIR", "action": "delete"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Garden.objects.filter(pk=self.garden.pk).exists())
        self.assertFalse(Device.objects.filter(pk=device.pk).exists())

    def test_unused_plan_and_its_versions_can_be_deleted(self):
        plan = Plan.objects.create(name="Plano de teste", code="delete-plan")
        PlanVersion.objects.create(
            plan=plan, version=1, price_cents=10000, effective_from=timezone.now()
        )
        response = self.client.post(
            reverse("ops-delete", args=["plans", plan.pk]),
            {"confirmation": "EXCLUIR", "action": "delete"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Plan.objects.filter(pk=plan.pk).exists())

    def test_used_crop_is_deactivated_instead_of_silently_deleted(self):
        crop = Crop.objects.create(common_name="Usada", code="crop-used")
        cultivar = Cultivar.objects.create(crop=crop, name="Comum")
        module_type = ModuleType.objects.create(name="Vaso", code="delete-pot")
        module = GardenModule.objects.create(
            organization=self.organization, module_type=module_type,
            serial_number="DELETE-MODULE", name="Módulo",
        )
        PlantingCycle.objects.create(
            organization=self.organization, garden=self.garden, module=module,
            crop=crop, cultivar=cultivar, status=PlantingCycle.Status.ACTIVE,
        )
        url = reverse("ops-delete", args=["crops", crop.pk])
        response = self.client.post(url, {"action": "delete", "confirmation": "EXCLUIR"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Crop.objects.filter(pk=crop.pk).exists())
        response = self.client.post(url, {"action": "deactivate"})
        self.assertEqual(response.status_code, 302)
        crop.refresh_from_db()
        self.assertFalse(crop.is_available)

    def test_employee_with_history_is_deactivated_and_visit_is_preserved(self):
        visit = Visit.objects.create(
            organization=self.organization, garden=self.garden, technician=self.technician,
            visit_type="Manutenção", scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
        )
        response = self.client.post(
            reverse("ops-delete", args=["employees", self.technician.pk]), {"action": "deactivate"}
        )
        self.assertEqual(response.status_code, 302)
        self.technician.refresh_from_db()
        visit.refresh_from_db()
        self.assertFalse(self.technician.is_active)
        self.assertEqual(visit.technician, self.technician)

    def test_failure_rolls_back_complete_customer_delete(self):
        garden_pk = self.garden.pk
        with patch.object(Organization, "delete", side_effect=RuntimeError("forced failure")):
            with self.assertRaises(RuntimeError):
                delete_customer_completely(self.customer)
        self.assertTrue(User.objects.filter(pk=self.customer.pk).exists())
        self.assertTrue(Garden.objects.filter(pk=garden_pk).exists())
