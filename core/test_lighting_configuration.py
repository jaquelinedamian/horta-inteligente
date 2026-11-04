from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Organization, User
from crops.models import Crop, CropLightingSchedule, Cultivar, PlantingCycle
from devices.models import Device, DeviceCommand, DeviceModel, LightingSchedule
from devices.services import schedule_lighting
from gardens.configuration import effective_garden_configuration
from gardens.models import Garden, GardenModule, ModuleType
from core.garden_experience import mark_custom_lighting_configuration, restore_crop_lighting_configuration
from core.backoffice_forms import CropLightingScheduleForm


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

    def test_species_form_calculates_end_time_from_daily_duration(self):
        lettuce = Crop.objects.get(code="alface")
        form = CropLightingScheduleForm({
            "crop": lettuce.pk, "start_time": "06:00", "duration_hours": "12", "enabled": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        schedule = form.save()
        self.assertEqual(schedule.end_time, time(18, 0))
        self.assertEqual(schedule.days_of_week, list(range(7)))
        lettuce.refresh_from_db()
        self.assertEqual(float(lettuce.light_hours), 12)

    def test_species_form_calculates_end_time_after_midnight(self):
        thyme = Crop.objects.get(code="tomilho")
        form = CropLightingScheduleForm({
            "crop": thyme.pk, "start_time": "18:00", "duration_hours": "12", "enabled": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        schedule = form.save()
        self.assertEqual(schedule.end_time, time(6, 0))
        self.assertEqual(schedule.duration_hours, 12)

    def test_species_form_exposes_only_simplified_portuguese_fields(self):
        form = CropLightingScheduleForm()
        self.assertEqual(list(form.fields), ["crop", "start_time", "duration_hours", "enabled"])
        self.assertEqual(form.fields["crop"].label, "Espécie")
        for removed in ("name", "timezone", "days_of_week", "end_time"):
            self.assertNotIn(removed, form.fields)

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

    def test_equal_start_and_end_is_a_24_hour_schedule(self):
        LightingSchedule.objects.create(
            actuator=self.light, name="24 horas", start_time=time(16, 45), end_time=time(16, 45),
            days_of_week=[0], enabled=True,
        )
        monday = datetime(2026, 11, 2, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

        self.assertEqual(schedule_lighting(now=monday), 1)

        command = DeviceCommand.objects.get(channel=self.light)
        self.assertTrue(command.payload["on"])
        self.assertEqual(command.payload["source"], "lighting_schedule")

    def test_24_hour_schedule_stays_on_at_every_time_of_enabled_day(self):
        schedule = LightingSchedule.objects.create(
            actuator=self.light, name="24 horas", start_time=time(16, 45), end_time=time(16, 45),
            days_of_week=[0], enabled=True,
        )
        for hour, minute in ((0, 0), (16, 45), (23, 59)):
            with self.subTest(hour=hour, minute=minute):
                DeviceCommand.objects.all().delete()
                now = datetime(2026, 11, 2, hour, minute, tzinfo=ZoneInfo("America/Sao_Paulo"))
                self.assertEqual(schedule_lighting(now=now), 1)
                command = DeviceCommand.objects.get(channel=self.light)
                self.assertTrue(command.payload["on"])
                self.assertIn(str(schedule.id), command.idempotency_key)
