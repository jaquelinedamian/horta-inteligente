from datetime import time

from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization, User
from crops.models import Crop, CropLightingSchedule, Cultivar, PlantingCycle
from devices.models import Device, DeviceModel, LightingSchedule
from gardens.configuration import effective_garden_configuration
from gardens.models import Garden, GardenModule, ModuleType
from core.garden_experience import mark_custom_lighting_configuration, restore_crop_lighting_configuration


class LightingConfigurationInheritanceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="light-owner@test.local", password="test")
        self.admin = User.objects.create_user(
            email="light-admin@test.local", password="test", employee_role=User.EmployeeRole.ADMIN
        )
        self.org = Organization.objects.create(name="Cliente luz", slug="cliente-luz")
        Membership.objects.create(user=self.owner, organization=self.org, role=Membership.Role.OWNER)
        self.garden = Garden.objects.create(organization=self.org, name="Horta luz", code="horta-luz")
        module_type = ModuleType.objects.create(name="Módulo", code="modulo-luz")
        module = GardenModule.objects.create(
            organization=self.org, module_type=module_type, serial_number="LIGHT-MOD-1", name="Módulo"
        )
        self.crop = Crop.objects.create(common_name="Manjericão", code="manjericao-light")
        cultivar = Cultivar.objects.create(crop=self.crop, name="Genovês")
        PlantingCycle.objects.create(
            organization=self.org, garden=self.garden, module=module, crop=self.crop,
            cultivar=cultivar, status=PlantingCycle.Status.ACTIVE,
        )
        self.default = CropLightingSchedule.objects.create(
            crop=self.crop, start_time=time(6), end_time=time(18),
            days_of_week=list(range(7)), enabled=True, updated_by=self.admin,
        )
        hardware = DeviceModel.objects.create(name="ESP Luz", code="esp-light-config")
        self.device = Device.objects.create(
            organization=self.org, garden=self.garden, model=hardware,
            serial_number="LIGHT-CONTROLLER-1", name="Controlador",
        )
        self.light = self.device.channels.get(metric="light_state")
        self.light.is_enabled = True
        self.light.save(update_fields=["is_enabled", "updated_at"])

    def test_default_is_inherited_dynamically(self):
        config = effective_garden_configuration(self.garden)["lighting"]
        self.assertEqual(config["source"], "crop_default")
        self.assertEqual(config["schedules"][0]["start"], "06:00")

        self.default.start_time = time(7)
        self.default.save(update_fields=["start_time", "updated_at"])
        self.assertEqual(effective_garden_configuration(self.garden)["lighting"]["schedules"][0]["start"], "07:00")

    def test_custom_schedule_is_not_changed_by_default_update(self):
        custom = LightingSchedule.objects.create(
            actuator=self.light, name="Personalizada", start_time=time(8), end_time=time(16),
            days_of_week=[0, 1, 2, 3, 4], enabled=True,
        )
        mark_custom_lighting_configuration(garden=self.garden, user=self.owner)
        self.default.start_time = time(9)
        self.default.save(update_fields=["start_time", "updated_at"])

        config = effective_garden_configuration(self.garden)["lighting"]
        self.assertEqual(config["source"], "custom")
        self.assertEqual(config["schedules"][0]["id"], str(custom.id))
        self.assertEqual(config["recommended_schedules"][0]["start"], "09:00")

    def test_restore_removes_override_and_returns_to_current_default(self):
        LightingSchedule.objects.create(
            actuator=self.light, name="Personalizada", start_time=time(8), end_time=time(16),
            days_of_week=list(range(7)), enabled=True,
        )
        mark_custom_lighting_configuration(garden=self.garden, user=self.owner)
        restore_crop_lighting_configuration(garden=self.garden, user=self.owner)

        self.garden.refresh_from_db()
        self.assertFalse(self.light.lighting_schedules.exists())
        self.assertEqual(effective_garden_configuration(self.garden)["lighting"]["source"], "crop_default")
        self.assertEqual(self.garden.configuration_events.first().origin, "restore")

    def test_only_admin_can_manage_crop_defaults(self):
        create_url = reverse("ops-create", args=["crop-lighting"])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(create_url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(create_url).status_code, 200)

    def test_owner_can_create_custom_period_for_own_garden(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("garden-automation-update", args=[self.garden.pk]),
            {"action": "lighting_add", "start_time": "09:00", "duration_minutes": "480", "days_of_week": [0, 1, 2, 3, 4], "enabled": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.garden.refresh_from_db()
        self.assertEqual(self.garden.automation_overrides["lighting"]["source"], "custom")
        self.assertEqual(effective_garden_configuration(self.garden)["lighting"]["schedules"][0]["start"], "09:00")
