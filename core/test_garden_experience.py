from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Channel, Device, DeviceCommand, DeviceCredential, DeviceModel, GardenPhoto, TelemetryReading
from gardens.configuration import effective_garden_configuration
from gardens.models import Garden, GardenConfigurationEvent, GardenModel


class GardenExperienceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="experience-owner@test.local", password="test", full_name="Cliente")
        self.other = User.objects.create_user(email="experience-other@test.local", password="test", full_name="Outro")
        self.tech = User.objects.create_user(email="experience-tech@test.local", password="test", full_name="Técnico", employee_role=User.EmployeeRole.TECHNICIAN)
        self.admin = User.objects.create_user(email="experience-admin@test.local", password="test", full_name="Admin", employee_role=User.EmployeeRole.ADMIN)
        self.org = Organization.objects.create(name="Cliente", slug="experience-client")
        self.other_org = Organization.objects.create(name="Outro", slug="experience-other")
        Membership.objects.create(user=self.owner, organization=self.org, role=Membership.Role.OWNER)
        Membership.objects.create(user=self.other, organization=self.other_org, role=Membership.Role.OWNER)
        self.model = GardenModel.objects.create(name="HV", code="experience-hv", photos_per_day=4, light_hours_per_day=12, irrigation_frequency_count=2, pump_duration_seconds=20)
        self.garden = Garden.objects.create(organization=self.org, name="Horta", code="experience", garden_model=self.model, primary_technician=self.tech)
        self.foreign = Garden.objects.create(organization=self.other_org, name="Alheia", code="foreign")
        hardware = DeviceModel.objects.create(name="ESP", code="experience-esp")
        self.device = Device.objects.create(organization=self.org, garden=self.garden, model=hardware, serial_number="EXPERIENCE-1", name="Controlador")
        self.temperature = self.device.channels.get(metric="air_temperature")
        self.pump = self.device.channels.get(metric="pump_state")

    def _configuration_payload(self, **overrides):
        data = {"light_hours": "10", "irrigation_frequency_count": "3", "irrigation_frequency_period": "day", "pump_duration_seconds": "25", "photos_per_day": "6", "monitoring_interval_minutes": "60"}
        data.update(overrides)
        return data

    def test_gallery_without_photos_is_friendly(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("garden-gallery", args=[self.garden.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhuma fotografia disponível ainda")

    def test_gallery_filters_and_orders_multiple_photos(self):
        old = GardenPhoto.objects.create(garden=self.garden, device=self.device, captured_at=timezone.now() - timedelta(days=20), image_data=b"a", byte_size=1)
        recent = GardenPhoto.objects.create(garden=self.garden, device=self.device, captured_at=timezone.now() - timedelta(days=2), image_data=b"b", byte_size=1)
        self.client.force_login(self.owner)
        seven = self.client.get(reverse("garden-gallery", args=[self.garden.pk]) + "?period=7d&order=asc&limit=all")
        self.assertEqual(list(seven.context["photos"]), [recent])
        thirty = self.client.get(reverse("garden-gallery", args=[self.garden.pk]) + "?period=30d&order=asc&limit=all")
        self.assertEqual(list(thirty.context["photos"]), [old, recent])

    def test_gallery_permission_is_scoped(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("garden-gallery", args=[self.garden.pk])).status_code, 404)

    def test_customer_edits_own_garden_and_api_reflects_override(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("garden-configuration", args=[self.garden.pk]), self._configuration_payload())
        self.assertEqual(response.status_code, 302)
        self.garden.refresh_from_db()
        self.assertEqual(effective_garden_configuration(self.garden)["lighting"]["hours_per_day"], 10.0)
        self.model.refresh_from_db()
        self.assertEqual(float(self.model.light_hours_per_day), 12.0)
        _, token = DeviceCredential.issue(self.device)
        api = self.client.get(reverse("device_api:configuration"), HTTP_AUTHORIZATION=f"Device {token}", HTTP_X_DEVICE_ID=str(self.device.pk))
        self.assertEqual(api.json()["monitoring"]["interval_minutes"], 60)
        self.assertEqual(api.json()["camera"]["photos_per_day"], 6)

    def test_customer_cannot_edit_foreign_garden(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("garden-configuration", args=[self.foreign.pk]), self._configuration_payload()).status_code, 404)

    def test_technician_scope_and_admin_global_scope(self):
        self.client.force_login(self.tech)
        self.assertEqual(self.client.post(reverse("garden-configuration", args=[self.garden.pk]), self._configuration_payload()).status_code, 302)
        self.assertEqual(self.client.get(reverse("garden-configuration", args=[self.foreign.pk])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("garden-configuration", args=[self.foreign.pk]), self._configuration_payload()).status_code, 302)

    def test_invalid_safety_limits_are_rejected(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("garden-configuration", args=[self.garden.pk]), self._configuration_payload(light_hours="19", pump_duration_seconds="301", photos_per_day="25", monitoring_interval_minutes="10"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.garden.refresh_from_db()
        self.assertFalse(self.garden.automation_overrides)

    def test_restore_requires_confirmation_post_and_records_history(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("garden-configuration", args=[self.garden.pk]), self._configuration_payload())
        url = reverse("garden-configuration-restore", args=[self.garden.pk])
        self.assertContains(self.client.get(url), "Restaurar as configurações padrão")
        self.garden.refresh_from_db()
        self.assertTrue(self.garden.automation_overrides)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.garden.refresh_from_db()
        self.assertFalse(self.garden.automation_overrides)
        self.assertEqual(effective_garden_configuration(self.garden)["lighting"]["hours_per_day"], 12.0)
        self.assertEqual(GardenConfigurationEvent.objects.filter(garden=self.garden).count(), 2)

    def test_reports_without_data_and_legacy_garden_return_200(self):
        legacy = Garden.objects.create(organization=self.org, name="Legada", code="legacy", automation_overrides=["old"])
        self.client.force_login(self.owner)
        for period in ("24h", "7d", "30d"):
            response = self.client.get(reverse("garden-reports", args=[legacy.pk]) + f"?period={period}")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Sensor de umidade não configurado")

    def test_reports_temperature_humidity_irrigation_and_photos(self):
        humidity = Channel.objects.create(device=self.device, key="humidity", name="Umidade", kind=Channel.Kind.SENSOR, metric="air_humidity", unit="%")
        now = timezone.now()
        TelemetryReading.objects.create(channel=self.temperature, recorded_at=now, decimal_value=25, idempotency_key="temp-report")
        TelemetryReading.objects.create(channel=humidity, recorded_at=now, decimal_value=70, idempotency_key="humidity-report")
        DeviceCommand.objects.create(device=self.device, channel=self.pump, command_type="set_state", payload={"duration_seconds": 20}, idempotency_key="irrigation-report")
        GardenPhoto.objects.create(garden=self.garden, device=self.device, captured_at=now, image_data=b"x", byte_size=1)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("garden-reports", args=[self.garden.pk]) + "?period=24h")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"]["irrigation_count"], 1)
        self.assertEqual(response.context["report"]["photo_count"], 1)
        self.assertEqual(response.context["report"]["sensors"]["air_temperature"]["average"], 25)
        self.assertEqual(response.context["report"]["sensors"]["air_humidity"]["average"], 70)

    def test_report_permission_is_scoped_and_admin_can_view_any(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("garden-reports", args=[self.garden.pk])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("garden-reports", args=[self.garden.pk])).status_code, 200)
