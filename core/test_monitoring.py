from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Channel, Device, DeviceCommand, DeviceModel, TelemetryReading
from gardens.models import Garden, GardenModel


class MonitoringExperienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="monitor@example.com", password="secret", full_name="Monitor")
        cls.org = Organization.objects.create(name="Monitor Org", slug="monitor-org")
        Membership.objects.create(organization=cls.org, user=cls.user, role=Membership.Role.OWNER)
        model = GardenModel.objects.create(name="Modelo", code="monitor-model", monitoring_interval_minutes=15)
        cls.garden = Garden.objects.create(organization=cls.org, garden_model=model, name="Horta", code="horta", status=Garden.Status.INSTALLED)
        device_model = DeviceModel.objects.create(name="ESP", code="monitor-esp")
        cls.device = Device.objects.create(organization=cls.org, garden=cls.garden, model=device_model, serial_number="MON-1", name="Controlador")
        cls.temperature, _ = Channel.objects.get_or_create(device=cls.device, metric="air_temperature", defaults={"key": "temperature", "name": "Temperatura", "kind": Channel.Kind.SENSOR, "unit": "°C"})
        cls.pump, _ = Channel.objects.get_or_create(device=cls.device, metric="pump_state", defaults={"key": "pump", "name": "Bomba", "kind": Channel.Kind.ACTUATOR})
        now = timezone.now()
        TelemetryReading.objects.create(channel=cls.temperature, recorded_at=now - timedelta(minutes=10), decimal_value=Decimal("22.0"), idempotency_key="temp-1")
        TelemetryReading.objects.create(channel=cls.temperature, recorded_at=now - timedelta(minutes=2), decimal_value=Decimal("24.0"), idempotency_key="temp-2")
        DeviceCommand.objects.create(device=cls.device, channel=cls.pump, command_type="set_state", payload={"on": True, "duration_seconds": 10}, status=DeviceCommand.Status.SUCCEEDED, acknowledged_at=now - timedelta(minutes=1), idempotency_key="pump-1")

    def setUp(self):
        self.client.force_login(self.user)

    def test_latest_api_exposes_real_value_timestamp_delta_and_freshness(self):
        response = self.client.get(reverse("garden-measurements-latest-api", args=[self.garden.pk]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["sensors"]["air_temperature"]["current"], 24.0)
        self.assertEqual(payload["sensors"]["air_temperature"]["delta"], 2.0)
        self.assertFalse(payload["is_stale"])
        self.assertEqual(payload["monitoring_interval_minutes"], 15)

    def test_history_api_aggregates_and_only_returns_real_ack_events(self):
        response = self.client.get(reverse("garden-measurements-api", args=[self.garden.pk]), {"period": "24h"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["aggregation"], "hour")
        self.assertTrue(payload["sensors"]["air_temperature"]["points"])
        self.assertEqual(payload["events"][0]["metric"], "pump_state")
        self.assertTrue(payload["events"][0]["on"])

    def test_custom_range_requires_valid_dates(self):
        response = self.client.get(reverse("garden-measurements-api", args=[self.garden.pk]), {"period": "custom"})
        self.assertEqual(response.status_code, 400)

    def test_other_customer_cannot_read_garden_measurements(self):
        other = User.objects.create_user(email="other@example.com", password="secret", full_name="Other")
        other_org = Organization.objects.create(name="Other", slug="other-monitor")
        Membership.objects.create(organization=other_org, user=other, role=Membership.Role.OWNER)
        self.client.force_login(other)
        response = self.client.get(reverse("garden-measurements-api", args=[self.garden.pk]))
        self.assertEqual(response.status_code, 404)
