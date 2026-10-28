import json
import re
from pathlib import Path
from unittest.mock import patch
from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Organization
from crops.models import Crop, CropCultivationProfile, Cultivar, PlantingCycle
from gardens.models import Garden, GardenModule, ModuleInstallation, ModuleType
from devices.models import Channel, Device, DeviceCommand, DeviceCredential, DeviceModel, GardenPhoto, IrrigationSchedule, LightingSchedule, TelemetryReading


class FirmwareLightingCommandContractTests(TestCase):
    def test_grow_light_set_state_on_is_accepted_and_acknowledged(self):
        firmware = (
            Path(__file__).resolve().parents[1]
            / "firmware"
            / "horta_inteligente_local"
            / "horta_inteligente_local.ino"
        ).read_text(encoding="utf-8")

        self.assertRegex(
            firmware,
            re.compile(
                r'channel\s*==\s*"lamp"\s*\|\|\s*channel\s*==\s*"grow-light"'
            ),
        )
        self.assertIn('lightStateItem["channel"] =', firmware)
        self.assertIn('"grow-light"', firmware)
        self.assertIn('lightStateItem["value"] =', firmware)
        self.assertIn('lampOn;', firmware)
        self.assertIn("bool readRelayState(uint8_t pin)", firmware)
        self.assertRegex(firmware, re.compile(r"RELAY_ACTIVE_LOW\s*\?\s*!gpioHigh\s*:\s*gpioHigh"))
        self.assertRegex(
            firmware,
            re.compile(r'setLamp\s*\(\s*on\s*,\s*"COMMAND"\s*\)'),
        )
        self.assertIn("gpioMatchesRequest", firmware)
        self.assertRegex(firmware, re.compile(r"acknowledge\s*\(\s*id\s*,\s*gpioMatchesRequest"))
        self.assertIn('"LIGHT_PIN: D6 / GPIO %u\\n"', firmware)
        self.assertIn('F("LIGHT CHANGE SOURCE: ")', firmware)
        self.assertLess(
            firmware.index("digitalWrite(LAMP_RELAY_PIN, RELAY_OFF_LEVEL);"),
            firmware.index("pinMode(LAMP_RELAY_PIN, OUTPUT);"),
        )

    def test_manual_command_polling_has_priority_and_bounded_timeouts(self):
        firmware = (
            Path(__file__).resolve().parents[1]
            / "firmware" / "horta_inteligente_local" / "horta_inteligente_local.ino"
        ).read_text(encoding="utf-8")
        self.assertIn("#define COMMAND_POLL_INTERVAL_MS 1000UL", firmware)
        self.assertNotIn("http.setTimeout(\n      70000", firmware)
        self.assertIn('"HTTP %s: %lu ms\\n"', firmware)
        self.assertIn('F("COMMAND LATENCY")', firmware)
        self.assertIn('secure.setSession(', firmware)
        self.assertIn('http.collectHeaders(responseHeaders, 1)', firmware)
        self.assertIn('"HTTP backend Server-Timing: "', firmware)
        loop = firmware[firmware.index("void loop()") :]
        self.assertLess(loop.index("pollCommands();"), loop.index("sendTelemetry();"))


class DeviceApiTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Cliente", slug="cliente")
        self.garden = Garden.objects.create(organization=self.organization, name="Horta", code="horta")
        model = DeviceModel.objects.create(name="Wemos D1 Mini", code="wemos", hardware_platform="ESP8266")
        self.device = Device.objects.create(organization=self.organization, garden=self.garden, model=model, serial_number="ESP-1", name="Controlador")
        self.temperature_channel = self.device.channels.get(key="air-temperature")
        self.pressure_channel = self.device.channels.get(key="air-pressure")
        self.actuator = self.device.channels.get(key="pump")
        _, self.token = DeviceCredential.issue(self.device)
        self.headers = {"HTTP_AUTHORIZATION": f"Device {self.token}"}
        self.command_headers = {
            **self.headers,
            "HTTP_X_DEVICE_ID": str(self.device.id),
        }

    def test_credentials_are_required(self):
        response = self.client.get(reverse("devices:commands"))
        self.assertEqual(response.status_code, 401)

    def test_telemetry_ingestion_is_idempotent(self):
        payload = {"readings": [
            {
                "channel": "air-temperature", "value": 24.5,
                "recorded_at": timezone.now().isoformat(), "idempotency_key": "sample-temperature-1",
            },
            {
                "channel": "air-pressure", "value": 1008.4,
                "recorded_at": timezone.now().isoformat(), "idempotency_key": "sample-pressure-1",
            },
        ]}
        first = self.client.post(reverse("devices:telemetry"), json.dumps(payload), content_type="application/json", **self.headers)
        second = self.client.post(reverse("devices:telemetry"), json.dumps(payload), content_type="application/json", **self.headers)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(TelemetryReading.objects.count(), 2)
        self.assertFalse(second.json()["readings"][0]["created"])
        self.assertFalse(second.json()["readings"][1]["created"])

    def test_telemetry_rejects_a_channel_key_not_registered_for_device(self):
        payload = {"readings": [{
            "channel": "temperature", "value": 24.5,
            "recorded_at": timezone.now().isoformat(), "idempotency_key": "legacy-temperature-1",
        }]}
        response = self.client.post(
            reverse("devices:telemetry"), json.dumps(payload),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["detail"],
            "canal desconhecido ou desabilitado: temperature",
        )

    def test_telemetry_persists_confirmed_boolean_actuator_states(self):
        payload = {"readings": [
            {"channel": "pump", "value": False, "recorded_at": timezone.now().isoformat(), "idempotency_key": "pump-state-1"},
            {"channel": "grow-light", "value": True, "recorded_at": timezone.now().isoformat(), "idempotency_key": "light-state-1"},
        ]}
        response = self.client.post(reverse("devices:telemetry"), json.dumps(payload), content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 202)
        self.assertIs(TelemetryReading.objects.get(channel__key="pump").boolean_value, False)
        self.assertIs(TelemetryReading.objects.get(channel__key="grow-light").boolean_value, True)

    def test_device_can_poll_and_acknowledge_its_command(self):
        command = DeviceCommand.objects.create(
            device=self.device, channel=self.actuator, command_type="set_state",
            payload={"on": True}, idempotency_key="pump-on-1", expires_at=timezone.now() + timedelta(minutes=5),
        )
        response = self.client.get(reverse("devices:commands"), **self.command_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commands"][0]["id"], str(command.id))
        response = self.client.post(
            reverse("devices:acknowledge-command", args=[command.id]),
            json.dumps({"status": "succeeded", "result": {"relay": True}}),
            content_type="application/json", **self.command_headers,
        )
        self.assertEqual(response.status_code, 200)
        command.refresh_from_db()
        self.assertEqual(command.status, DeviceCommand.Status.SUCCEEDED)

    def test_light_command_uses_firmware_contract_and_acknowledges_lamp_state(self):
        light = self.device.channels.get(metric="light_state")
        command = DeviceCommand.objects.create(
            device=self.device, channel=light, command_type="set_state",
            payload={"on": False}, idempotency_key="lamp-off-1",
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.get(reverse("devices:commands"), **self.command_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commands"][0]["channel"], "grow-light")
        self.assertEqual(response.json()["commands"][0]["type"], "set_state")
        self.assertFalse(response.json()["commands"][0]["payload"]["on"])

        response = self.client.post(
            reverse("devices:acknowledge-command", args=[command.id]),
            json.dumps({"status": "succeeded", "result": {"lamp": False}}),
            content_type="application/json", **self.command_headers,
        )

        self.assertEqual(response.status_code, 200)
        command.refresh_from_db()
        self.assertEqual(command.result["lamp"], False)
        self.assertEqual(command.result["relay"], False)
        confirmation = TelemetryReading.objects.get(channel=light, idempotency_key=f"ack:{command.id}")
        self.assertIs(confirmation.boolean_value, False)

    def test_unacknowledged_command_is_redelivered_until_ack(self):
        command = DeviceCommand.objects.create(
            device=self.device, channel=self.actuator, command_type="set_state",
            payload={"on": False}, idempotency_key="retry-pump-off",
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        first = self.client.get(reverse("devices:commands"), **self.command_headers)
        second = self.client.get(reverse("devices:commands"), **self.command_headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["commands"][0]["id"], str(command.id))
        self.assertEqual(second.json()["commands"][0]["id"], str(command.id))
        command.refresh_from_db()
        self.assertEqual(command.status, DeviceCommand.Status.DELIVERED)

    def test_expired_command_is_not_delivered(self):
        command = DeviceCommand.objects.create(
            device=self.device, channel=self.actuator, command_type="set_state",
            payload={"on": True}, idempotency_key="expired-pump-on",
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.client.get(reverse("devices:commands"), **self.command_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commands"], [])
        command.refresh_from_db()
        self.assertEqual(command.status, DeviceCommand.Status.EXPIRED)

    def test_pump_ack_normalizes_physical_state_for_the_ui(self):
        command = DeviceCommand.objects.create(
            device=self.device, channel=self.actuator, command_type="set_state",
            payload={"on": True}, idempotency_key="pump-normalized-1",
            status=DeviceCommand.Status.DELIVERED,
            delivered_at=timezone.now(), expires_at=timezone.now() + timedelta(minutes=5),
        )
        response = self.client.post(
            reverse("devices:acknowledge-command", args=[command.id]),
            json.dumps({"status": "succeeded", "result": {"pump": True}}),
            content_type="application/json", **self.command_headers,
        )
        self.assertEqual(response.status_code, 200)
        command.refresh_from_db()
        self.assertIs(command.result["relay"], True)

    def test_commands_reject_token_and_device_id_mismatch(self):
        response = self.client.get(
            reverse("devices:commands"),
            HTTP_AUTHORIZATION=f"Device {self.token}",
            HTTP_X_DEVICE_ID="00000000-0000-0000-0000-000000000000",
        )

        self.assertEqual(response.status_code, 403)

    def test_authentication_logs_safe_reason_for_existing_prefix_with_wrong_secret(self):
        prefix = self.token.split(".", 1)[0]

        with patch("devices.authentication.logger.warning") as warning:
            response = self.client.get(
                reverse("devices:commands"),
                HTTP_AUTHORIZATION=f"Device {prefix}.segredo-incorreto",
                HTTP_X_DEVICE_ID=str(self.device.id),
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("secret_hash_mismatch", warning.call_args.args)
        logged = " ".join(str(value) for value in warning.call_args.args)
        self.assertIn(prefix, logged)
        self.assertNotIn("segredo-incorreto", logged)

    def test_authorization_scheme_is_case_insensitive(self):
        response = self.client.get(
            reverse("devices:commands"),
            HTTP_AUTHORIZATION=f"device {self.token}",
            HTTP_X_DEVICE_ID=str(self.device.id),
        )

        self.assertEqual(response.status_code, 200)

    def test_simplified_telemetry_validates_device_id(self):
        response = self.client.post(
            reverse("device_api:telemetry"),
            json.dumps({"device_id": "OUTRO", "temperature": 24.5}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            reverse("device_api:telemetry"),
            json.dumps({"device_id": str(self.device.id), "temperature": 24.5}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(response.status_code, 202)

    def test_camera_upload_requires_camera_credential_and_saves_jpeg(self):
        model = DeviceModel.objects.create(name="ESP32-CAM", code="camera", hardware_platform="ESP32")
        camera = Device.objects.create(organization=self.organization, garden=self.garden, model=model, serial_number="CAM-1", name="Câmera", kind=Device.Kind.CAMERA)
        _, token = DeviceCredential.issue(camera)
        response = self.client.post(
            reverse("device_api:photo"), b"\xff\xd8jpeg-test\xff\xd9", content_type="image/jpeg",
            HTTP_AUTHORIZATION=f"Device {token}", HTTP_X_DEVICE_ID=str(camera.id),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(GardenPhoto.objects.filter(garden=self.garden, device=camera).count(), 1)
        camera.refresh_from_db()
        self.assertEqual(camera.status, Device.Status.ONLINE)
        self.assertIsNotNone(camera.last_seen_at)

    def test_photo_rejects_wrong_uuid_even_with_valid_camera_token(self):
        model = DeviceModel.objects.create(name="ESP32-CAM UUID", code="camera-uuid", hardware_platform="ESP32")
        camera = Device.objects.create(
            organization=self.organization, garden=self.garden, model=model,
            serial_number="CAM-UUID", name="Camera UUID", kind=Device.Kind.CAMERA,
        )
        _, token = DeviceCredential.issue(camera)
        response = self.client.post(
            reverse("device_api:photo"), b"\xff\xd8jpeg-test\xff\xd9", content_type="image/jpeg",
            HTTP_AUTHORIZATION=f"Device {token}", HTTP_X_DEVICE_ID=str(self.device.id),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(GardenPhoto.objects.filter(device=camera).exists())

    def test_controller_cannot_use_photo_endpoint(self):
        response = self.client.post(
            reverse("device_api:photo"), b"\xff\xd8jpeg-test\xff\xd9", content_type="image/jpeg",
            HTTP_X_DEVICE_ID=str(self.device.id), **self.headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_camera_credential_cannot_represent_controller_uuid(self):
        model = DeviceModel.objects.create(name="ESP32-CAM Bound", code="camera-bound", hardware_platform="ESP32")
        camera = Device.objects.create(
            organization=self.organization, garden=self.garden, model=model,
            serial_number="CAM-BOUND", name="Camera Bound", kind=Device.Kind.CAMERA,
        )
        _, camera_token = DeviceCredential.issue(camera)
        response = self.client.post(
            reverse("device_api:photo"), b"\xff\xd8jpeg-test\xff\xd9", content_type="image/jpeg",
            HTTP_AUTHORIZATION=f"Device {camera_token}", HTTP_X_DEVICE_ID=str(self.device.id),
        )
        self.assertEqual(response.status_code, 403)

    def test_photo_rejects_truncated_jpeg(self):
        model = DeviceModel.objects.create(name="ESP32-CAM JPEG", code="camera-jpeg", hardware_platform="ESP32")
        camera = Device.objects.create(
            organization=self.organization, garden=self.garden, model=model,
            serial_number="CAM-JPEG", name="Camera JPEG", kind=Device.Kind.CAMERA,
        )
        _, token = DeviceCredential.issue(camera)
        response = self.client.post(
            reverse("device_api:photo"), b"\xff\xd8not-complete", content_type="image/jpeg",
            HTTP_AUTHORIZATION=f"Device {token}", HTTP_X_DEVICE_ID=str(camera.id),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(GardenPhoto.objects.filter(device=camera).exists())

    def test_controller_and_camera_share_garden_with_independent_credentials(self):
        camera_model = DeviceModel.objects.create(name="ESP32-CAM", code="camera-independent", hardware_platform="ESP32")
        camera = Device.objects.create(
            organization=self.organization, garden=self.garden, model=camera_model,
            serial_number="CAM-INDEPENDENT", name="Câmera", kind=Device.Kind.CAMERA,
        )
        _, camera_token = DeviceCredential.issue(camera)
        self.assertEqual(self.device.assigned_garden(), self.garden)
        self.assertEqual(camera.assigned_garden(), self.garden)
        self.assertNotEqual(self.token, camera_token)
        self.assertEqual(self.device.credentials.count(), 1)
        self.assertEqual(camera.credentials.count(), 1)

    def test_configuration_merges_crop_defaults_and_garden_override(self):
        crop, _ = Crop.objects.update_or_create(code="cebolinha", defaults={"common_name": "Cebolinha"})
        cultivar = Cultivar.objects.create(crop=crop, name="Comum")
        profile = CropCultivationProfile.objects.create(
            crop=crop, cultivation_system="substrate", name="Padrão",
            automation_config={"irrigation": {"enabled": True, "times": ["08:00"], "duration_seconds": 30}},
        )
        module_type = ModuleType.objects.create(name="Módulo", code="modulo")
        module = GardenModule.objects.create(organization=self.organization, module_type=module_type, serial_number="M-1", name="Módulo")
        ModuleInstallation.objects.create(module=module, garden=self.garden, installed_at=timezone.now())
        PlantingCycle.objects.create(organization=self.organization, garden=self.garden, module=module, crop=crop, cultivar=cultivar, cultivation_profile=profile, status=PlantingCycle.Status.ACTIVE)
        self.garden.automation_overrides = {"irrigation": {"duration_seconds": 45}}
        self.garden.save(update_fields=["automation_overrides"])
        response = self.client.get(reverse("device_api:configuration"), HTTP_X_DEVICE_ID=str(self.device.id), **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["irrigation"]["enabled"])
        self.assertEqual(response.json()["irrigation"]["times"], ["08:00"])
        self.assertEqual(response.json()["irrigation"]["duration_seconds"], 45)
        self.assertEqual(response.json()["irrigation"]["schedules"], [])

    def test_soil_moisture_telemetry_keeps_percent_and_raw(self):
        payload = {"readings": [{
            "channel": "soil-moisture", "value": 64,
            "recorded_at": timezone.now().isoformat(), "idempotency_key": "soil-1",
            "raw": {"raw": 712},
        }]}
        response = self.client.post(reverse("devices:telemetry"), json.dumps(payload), content_type="application/json", **self.headers)
        self.assertEqual(response.status_code, 202)
        reading = TelemetryReading.objects.get(channel__key="soil-moisture")
        self.assertEqual(reading.decimal_value, 64)
        self.assertEqual(reading.raw["raw"], 712)

    def test_configuration_contains_calibration_and_schedules(self):
        pump = self.device.channels.get(key="pump")
        IrrigationSchedule.objects.create(
            actuator=pump, start_time="07:00", duration_seconds=10,
            days_of_week=[0, 1, 2, 3, 4, 5, 6], enabled=True,
        )
        response = self.client.get(reverse("device_api:configuration"), HTTP_X_DEVICE_ID=str(self.device.id), **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["soil_moisture"], {"dry_raw": 850, "wet_raw": 350})
        self.assertEqual(response.json()["irrigation"]["schedules"][0]["duration_seconds"], 10)

    def test_configuration_rejects_device_id_from_another_controller(self):
        response = self.client.get(
            reverse("device_api:configuration"), HTTP_X_DEVICE_ID="00000000-0000-0000-0000-000000000000",
            **self.headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_configuration_serializes_lighting_summary_and_overnight_duration(self):
        light = self.device.channels.get(metric="light_state")
        LightingSchedule.objects.create(
            actuator=light, name="Noite", start_time=time(18), end_time=time(6),
            days_of_week=[0, 2, 4], enabled=True,
        )
        response = self.client.get(
            reverse("device_api:configuration"), HTTP_X_DEVICE_ID=str(self.device.id), **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        lighting = response.json()["lighting"]
        self.assertEqual(lighting["times"], ["18:00"])
        self.assertEqual(lighting["duration_seconds"], 43200)
        self.assertEqual(lighting["duration_hours"], 12)
        self.assertEqual(lighting["schedules"][0]["days"], [0, 2, 4])

    def test_configuration_api_never_returns_more_than_four_photos(self):
        self.garden.automation_overrides = {"camera": {"photos_per_day": 24}}
        self.garden.save(update_fields=["automation_overrides", "updated_at"])
        response = self.client.get(reverse("device_api:configuration"), HTTP_X_DEVICE_ID=str(self.device.id), **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["camera"]["photos_per_day"], 4)

    def test_configuration_api_defaults_to_four_photos(self):
        response = self.client.get(reverse("device_api:configuration"), HTTP_X_DEVICE_ID=str(self.device.id), **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["camera"]["photos_per_day"], 4)


class ControllerChannelProvisioningTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Cliente", slug="provisioning")
        self.model = DeviceModel.objects.create(name="Wemos D1 Mini", code="provisioning-wemos", hardware_platform="ESP8266")

    def test_new_controller_receives_standard_channels(self):
        device = Device.objects.create(
            organization=self.organization, model=self.model,
            serial_number="ESP-DEFAULTS", name="Controlador",
        )
        self.assertEqual(
            set(device.channels.values_list("key", flat=True)),
            {"air-temperature", "air-pressure", "soil-moisture", "pump", "grow-light"},
        )
        self.assertEqual(device.channels.get(key="air-temperature").metric, "air_temperature")
        self.assertEqual(device.channels.get(key="air-pressure").kind, Channel.Kind.SENSOR)
        self.assertEqual(device.channels.get(key="pump").kind, Channel.Kind.ACTUATOR)

    def test_ensure_defaults_is_idempotent_and_preserves_custom_channels(self):
        from devices.services import ensure_controller_default_channels

        device = Device.objects.create(
            organization=self.organization, model=self.model,
            serial_number="ESP-CUSTOM", name="Controlador",
        )
        custom = Channel.objects.create(device=device, key="custom-soil", name="Solo customizado", kind=Channel.Kind.SENSOR, metric="custom_soil")
        temperature = device.channels.get(key="air-temperature")
        temperature.name = "Sensor personalizado"
        temperature.is_enabled = False
        temperature.save(update_fields=["name", "is_enabled", "updated_at"])

        self.assertEqual(ensure_controller_default_channels(device), [])
        self.assertEqual(device.channels.count(), 6)
        temperature.refresh_from_db()
        self.assertEqual(temperature.name, "Sensor personalizado")
        self.assertFalse(temperature.is_enabled)
        self.assertTrue(Channel.objects.filter(pk=custom.pk).exists())

    def test_camera_does_not_receive_controller_channels(self):
        camera = Device.objects.create(
            organization=self.organization, model=self.model,
            serial_number="CAM-NO-DEFAULTS", name="Câmera", kind=Device.Kind.CAMERA,
        )
        self.assertFalse(camera.channels.exists())
