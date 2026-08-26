import json
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Organization
from devices.models import Channel, Device, DeviceCommand, DeviceCredential, DeviceModel, TelemetryReading


class DeviceApiTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Cliente", slug="cliente")
        model = DeviceModel.objects.create(name="Wemos D1 Mini", code="wemos", hardware_platform="ESP8266")
        self.device = Device.objects.create(organization=self.organization, model=model, serial_number="ESP-1", name="Controlador")
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
