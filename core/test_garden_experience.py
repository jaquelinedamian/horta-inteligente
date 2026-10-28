from datetime import time, timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import (Channel, Device, DeviceCommand, DeviceCredential, DeviceHeartbeat,
                            DeviceModel, GardenPhoto, IrrigationSchedule, LightingSchedule, TelemetryReading)
from devices.selectors import actuator_automation_summary, garden_snapshot
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
        data = {"light_hours": "10", "irrigation_frequency_count": "3", "irrigation_frequency_period": "day", "pump_duration_seconds": "25", "photos_per_day": "4", "monitoring_interval_minutes": "60"}
        data.update(overrides)
        return data

    def test_admin_issues_credential_once_without_revoking_previous(self):
        old, old_token = DeviceCredential.issue(self.device, name="anterior")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("garden-credential-issue", args=[self.garden.pk, self.device.pk]), {"name": "nova"})
        self.assertEqual(response.status_code, 200)
        old.refresh_from_db()
        self.assertTrue(old.is_active)
        self.assertContains(response, "não poderá ser exibido novamente")
        self.assertContains(response, '#define DEVICE_ID')
        self.assertNotContains(response, old_token)
        self.assertEqual(self.device.credentials.filter(is_active=True).count(), 2)

    def test_owner_cannot_issue_or_revoke_device_credentials(self):
        credential, _ = DeviceCredential.issue(self.device)
        self.client.force_login(self.owner)
        issue = self.client.post(reverse("garden-credential-issue", args=[self.garden.pk, self.device.pk]))
        revoke = self.client.post(reverse("garden-credential-revoke", args=[self.garden.pk, credential.pk]))
        self.assertEqual(issue.status_code, 403)
        self.assertEqual(revoke.status_code, 403)
        credential.refresh_from_db()
        self.assertTrue(credential.is_active)

    def test_credential_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(reverse("garden-credential-issue", args=[self.garden.pk, self.device.pk]))
        self.assertEqual(response.status_code, 403)

    def test_offline_controller_does_not_queue_manual_command(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("device-action"), {"channel": self.pump.pk, "action": "on", "next": reverse("garden-detail", args=[self.garden.pk])})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DeviceCommand.objects.filter(channel=self.pump).exists())

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
        self.assertEqual(api.json()["camera"]["photos_per_day"], 4)

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
        response = self.client.post(reverse("garden-configuration", args=[self.garden.pk]), self._configuration_payload(light_hours="19", pump_duration_seconds="301", photos_per_day="24", monitoring_interval_minutes="10"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.garden.refresh_from_db()
        self.assertFalse(self.garden.automation_overrides)

    def test_photo_frequency_accepts_only_product_choices(self):
        self.client.force_login(self.owner)
        for value in (1, 2, 3, 4):
            with self.subTest(value=value):
                response = self.client.post(
                    reverse("garden-configuration", args=[self.garden.pk]),
                    self._configuration_payload(photos_per_day=str(value)),
                )
                self.assertEqual(response.status_code, 302)
                self.garden.refresh_from_db()
                self.assertEqual(self.garden.automation_overrides["camera"]["photos_per_day"], value)
        for value in (5, 24):
            with self.subTest(value=value):
                response = self.client.post(
                    reverse("garden-configuration", args=[self.garden.pk]),
                    self._configuration_payload(photos_per_day=str(value)),
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("photos_per_day", response.context["form"].errors)

    def test_legacy_and_missing_photo_frequency_are_safe(self):
        self.model.photos_per_day = 24
        self.model.save(update_fields=["photos_per_day", "updated_at"])
        self.garden.automation_overrides = {"camera": {"photos_per_day": 24}}
        self.garden.save(update_fields=["automation_overrides", "updated_at"])
        self.assertEqual(effective_garden_configuration(self.garden)["camera"]["photos_per_day"], 4)

        self.garden.automation_overrides = {"camera": {}}
        self.garden.garden_model = None
        self.garden.save(update_fields=["automation_overrides", "garden_model", "updated_at"])
        self.assertEqual(effective_garden_configuration(self.garden)["camera"]["photos_per_day"], 4)

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
            self.assertContains(response, "Sensor de umidade do solo não configurado")

    def test_reports_temperature_soil_moisture_pressure_irrigation_and_photos(self):
        soil = self.device.channels.get(metric="soil_moisture")
        pressure = self.device.channels.get(metric="air_pressure")
        now = timezone.now()
        TelemetryReading.objects.create(channel=self.temperature, recorded_at=now, decimal_value=25, idempotency_key="temp-report")
        TelemetryReading.objects.create(channel=soil, recorded_at=now, decimal_value=70, idempotency_key="soil-report")
        TelemetryReading.objects.create(channel=pressure, recorded_at=now, decimal_value=934.5, idempotency_key="pressure-report")
        DeviceCommand.objects.create(device=self.device, channel=self.pump, command_type="set_state", payload={"duration_seconds": 20}, idempotency_key="irrigation-report")
        GardenPhoto.objects.create(garden=self.garden, device=self.device, captured_at=now, image_data=b"x", byte_size=1)
        self.client.force_login(self.owner)
        response = self.client.get(reverse("garden-reports", args=[self.garden.pk]) + "?period=24h")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report"]["irrigation_count"], 1)
        self.assertEqual(response.context["report"]["photo_count"], 1)
        self.assertEqual(response.context["report"]["sensors"]["air_temperature"]["average"], 25)
        self.assertEqual(response.context["report"]["sensors"]["soil_moisture"]["average"], 70)
        self.assertEqual(response.context["report"]["sensors"]["air_pressure"]["average"], 934.5)
        self.assertNotIn("air_humidity", response.context["report"]["sensors"])

    def test_snapshot_exposes_controller_sensor_metrics(self):
        now = timezone.now()
        soil = self.device.channels.get(metric="soil_moisture")
        pressure = self.device.channels.get(metric="air_pressure")
        TelemetryReading.objects.create(channel=self.temperature, recorded_at=now, decimal_value=24.3, idempotency_key="snapshot-temp")
        TelemetryReading.objects.create(channel=soil, recorded_at=now, decimal_value=68, idempotency_key="snapshot-soil")
        TelemetryReading.objects.create(channel=pressure, recorded_at=now, decimal_value=934.5, idempotency_key="snapshot-pressure")

        metrics = garden_snapshot(self.garden)["metrics"]

        self.assertEqual(float(metrics["air_temperature"]["value"]), 24.3)
        self.assertEqual(float(metrics["soil_moisture"]["value"]), 68)
        self.assertEqual(float(metrics["air_pressure"]["value"]), 934.5)

    def test_quick_control_summary_uses_real_schedules_heartbeat_and_history(self):
        now = timezone.now()
        self.device.last_seen_at = now
        self.device.status = Device.Status.ONLINE
        self.device.save(update_fields=["last_seen_at", "status", "updated_at"])
        light = self.device.channels.get(metric="light_state")
        IrrigationSchedule.objects.create(
            actuator=self.pump, name="Manhã", days_of_week=list(range(7)),
            start_time=time(7, 0), duration_seconds=20,
        )
        LightingSchedule.objects.create(
            actuator=light, name="Ciclo diário", days_of_week=list(range(7)),
            start_time=time(6, 0), end_time=time(18, 0),
        )
        DeviceHeartbeat.objects.create(
            device=self.device, recorded_at=now, diagnostics={"pump_on": True, "lamp_on": True},
        )
        DeviceCommand.objects.create(
            device=self.device, channel=self.pump, command_type="set_state",
            payload={"on": True, "duration_seconds": 20, "mode": "manual_safe"},
            status=DeviceCommand.Status.SUCCEEDED, acknowledged_at=now,
            result={"pump": True, "relay": True}, idempotency_key="summary-pump",
        )
        DeviceCommand.objects.create(
            device=self.device, channel=light, command_type="set_state",
            payload={"on": True, "duration_seconds": 3600, "mode": "manual"},
            status=DeviceCommand.Status.SUCCEEDED, acknowledged_at=now,
            result={"lamp": True, "relay": True}, idempotency_key="summary-light",
        )

        summary = actuator_automation_summary(garden_snapshot(self.garden))

        self.assertTrue(summary["irrigation"]["active"])
        self.assertEqual(summary["irrigation"]["daily_count"], 1)
        self.assertEqual(summary["irrigation"]["last_duration_seconds"], 20)
        self.assertEqual(summary["irrigation"]["last_origin"], "Manual")
        self.assertTrue(summary["lighting"]["active"])
        self.assertEqual(summary["lighting"]["hours_per_day"], 12)
        self.assertIn(summary["lighting"]["next_action"], {"Ligar", "Desligar"})

    def test_physical_state_confirmation_overrides_an_older_command(self):
        now = timezone.now()
        light = self.device.channels.get(metric="light_state")
        self.device.last_seen_at = now
        self.device.save(update_fields=["last_seen_at", "updated_at"])
        DeviceCommand.objects.create(
            device=self.device, channel=light, command_type="set_state", payload={"on": False},
            status=DeviceCommand.Status.SUCCEEDED, acknowledged_at=now - timedelta(minutes=2),
            result={"relay": False}, idempotency_key="older-off-command",
        )
        TelemetryReading.objects.create(
            channel=light, recorded_at=now, boolean_value=True, idempotency_key="physical-light-on",
        )

        summary = actuator_automation_summary(garden_snapshot(self.garden))

        self.assertIs(summary["lighting"]["state"], True)
        self.assertTrue(summary["lighting"]["state_is_recent"])
        self.assertEqual(summary["lighting"]["state_source"], "telemetry")

    def test_report_permission_is_scoped_and_admin_can_view_any(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("garden-reports", args=[self.garden.pk])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("garden-reports", args=[self.garden.pk])).status_code, 200)

    def test_customer_experience_has_new_sections_and_friendly_empty_states(self):
        self.garden.status = Garden.Status.INSTALLED
        self.garden.garden_model = None
        self.garden.save(update_fields=["status", "garden_model", "updated_at"])
        self.client.force_login(self.owner)

        dashboard = self.client.get(reverse("customer-dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        for text in ("Desenvolvimento da horta", "Configurações da horta", "Editar configurações", "Relatórios", "Padrão HortaViva"):
            self.assertContains(dashboard, text)
        for text in ("Nenhuma foto ainda", "Sensor ainda não disponível", "Iluminação não configurada", "Sem visita agendada", "Offline"):
            self.assertContains(dashboard, text)
        self.assertNotContains(dashboard, "Reservatório")
        self.assertContains(dashboard, "Desenvolvimento")
        self.assertNotContains(dashboard, "Minhas culturas</a>")

        garden_page = self.client.get(reverse("customer-section", args=["garden"]))
        self.assertEqual(garden_page.status_code, 200)
        self.assertContains(garden_page, "Nenhuma cultura plantada")
        self.assertContains(garden_page, "Iluminação não configurada")

    def test_customer_experience_shows_complete_and_personalized_garden(self):
        now = timezone.now()
        self.garden.status = Garden.Status.INSTALLED
        self.garden.automation_overrides = {"lighting": {"hours_per_day": 10}}
        self.garden.save(update_fields=["status", "automation_overrides", "updated_at"])
        self.device.last_seen_at = now
        self.device.status = Device.Status.ONLINE
        self.device.save(update_fields=["last_seen_at", "status", "updated_at"])
        soil = self.device.channels.get(metric="soil_moisture")
        pressure = self.device.channels.get(metric="air_pressure")
        Channel.objects.create(device=self.device, key="light-ui", name="Luz", kind=Channel.Kind.ACTUATOR, metric="light_state")
        TelemetryReading.objects.create(channel=self.temperature, recorded_at=now, decimal_value=24, idempotency_key="temp-ui")
        TelemetryReading.objects.create(channel=soil, recorded_at=now, decimal_value=68, idempotency_key="soil-ui")
        TelemetryReading.objects.create(channel=pressure, recorded_at=now, decimal_value=934.5, idempotency_key="pressure-ui")
        camera = Device.objects.create(organization=self.org, garden=self.garden, model=self.device.model, serial_number="EXPERIENCE-CAM", name="Câmera", kind=Device.Kind.CAMERA, status=Device.Status.ONLINE, last_seen_at=now)
        GardenPhoto.objects.create(garden=self.garden, device=camera, captured_at=now, image_data=b"photo", byte_size=5)

        self.client.force_login(self.owner)
        dashboard = self.client.get(reverse("customer-dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        for text in ("Online", "24", "68", "Personalizado", "Restaurar padrão", "Ver desenvolvimento"):
            self.assertContains(dashboard, text)
        self.assertEqual(self.client.get(reverse("customer-development")).status_code, 302)
        self.assertEqual(self.client.get(reverse("customer-history")).status_code, 200)
