import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Organization
from crops.models import Crop, CropCultivationProfile, Cultivar, PlantingCycle
from gardens.models import Garden, GardenModule, ModuleInstallation, ModuleType
from devices.models import Channel, Device, DeviceCommand, DeviceCredential, DeviceModel, GardenPhoto, TelemetryReading


class DeviceApiTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Cliente", slug="cliente")
        self.garden = Garden.objects.create(organization=self.organization, name="Horta", code="horta")
        model = DeviceModel.objects.create(name="Wemos D1 Mini", code="wemos", hardware_platform="ESP8266")
        self.device = Device.objects.create(organization=self.organization, garden=self.garden, model=model, serial_number="ESP-1", name="Controlador")
        self.channel = Channel.objects.create(device=self.device, key="temperature", name="Temperatura", kind="sensor", metric="air_temperature", unit="°C")
        self.actuator = Channel.objects.create(device=self.device, key="pump", name="Bomba", kind="actuator", metric="pump_state", value_type="boolean")
        _, self.token = DeviceCredential.issue(self.device)
        self.headers = {"HTTP_AUTHORIZATION": f"Device {self.token}"}

    def test_credentials_are_required(self):
        response = self.client.get(reverse("devices:commands"))
        self.assertEqual(response.status_code, 401)

    def test_telemetry_ingestion_is_idempotent(self):
        payload = {"readings": [{
            "channel": "temperature", "value": 24.5,
            "recorded_at": timezone.now().isoformat(), "idempotency_key": "sample-1",
        }]}
        first = self.client.post(reverse("devices:telemetry"), json.dumps(payload), content_type="application/json", **self.headers)
        second = self.client.post(reverse("devices:telemetry"), json.dumps(payload), content_type="application/json", **self.headers)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(TelemetryReading.objects.count(), 1)
        self.assertFalse(second.json()["readings"][0]["created"])

    def test_device_can_poll_and_acknowledge_its_command(self):
        command = DeviceCommand.objects.create(
            device=self.device, channel=self.actuator, command_type="set_state",
            payload={"on": True}, idempotency_key="pump-on-1", expires_at=timezone.now() + timedelta(minutes=5),
        )
        response = self.client.get(reverse("devices:commands"), **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["commands"][0]["id"], str(command.id))
        response = self.client.post(
            reverse("devices:acknowledge-command", args=[command.id]),
            json.dumps({"status": "succeeded", "result": {"relay": True}}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        command.refresh_from_db()
        self.assertEqual(command.status, DeviceCommand.Status.SUCCEEDED)

    def test_simplified_telemetry_validates_device_id(self):
        response = self.client.post(
            reverse("device_api:telemetry"),
            json.dumps({"device_id": "OUTRO", "temperature": 24.5}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            reverse("device_api:telemetry"),
            json.dumps({"device_id": self.device.serial_number, "temperature": 24.5}),
            content_type="application/json", **self.headers,
        )
        self.assertEqual(response.status_code, 202)

    def test_camera_upload_requires_camera_credential_and_saves_jpeg(self):
        model = DeviceModel.objects.create(name="ESP32-CAM", code="camera", hardware_platform="ESP32")
        camera = Device.objects.create(organization=self.organization, garden=self.garden, model=model, serial_number="CAM-1", name="Câmera", kind=Device.Kind.CAMERA)
        _, token = DeviceCredential.issue(camera)
        response = self.client.post(
            reverse("device_api:photo"), b"\xff\xd8jpeg-test\xff\xd9", content_type="image/jpeg",
            HTTP_AUTHORIZATION=f"Device {token}", HTTP_X_DEVICE_ID="CAM-1",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(GardenPhoto.objects.filter(garden=self.garden, device=camera).count(), 1)

    def test_configuration_merges_crop_defaults_and_garden_override(self):
        crop = Crop.objects.create(common_name="Cebolinha", code="cebolinha")
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
        response = self.client.get(reverse("device_api:configuration"), HTTP_X_DEVICE_ID="ESP-1", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["irrigation"], {"enabled": True, "times": ["08:00"], "duration_seconds": 45})
