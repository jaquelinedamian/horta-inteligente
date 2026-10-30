import re
from pathlib import Path

from django.test import TestCase
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Channel, Device, DeviceModel
from devices.selectors import actuator_automation_summary, garden_snapshot
from devices.services import queue_actuator_command
from gardens.models import Garden


class RelayFirmwareIsolationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.firmware = (
            Path(__file__).resolve().parents[1]
            / "firmware" / "esp8266-bmp280-relay" / "src" / "main.cpp"
        ).read_text(encoding="utf-8")

    def test_relay_pins_and_active_low_are_explicit(self):
        for declaration in (
            "constexpr uint8_t PUMP_RELAY_PIN = D5;",
            "constexpr uint8_t LIGHT_RELAY_PIN = D6;",
            "constexpr bool PUMP_RELAY_ACTIVE_LOW = true;",
            "constexpr bool LIGHT_RELAY_ACTIVE_LOW = true;",
        ):
            self.assertIn(declaration, self.firmware)

    def test_each_state_function_writes_only_its_own_gpio(self):
        pump = re.search(r"void setPumpState\(bool on\) \{(.*?)\n\}", self.firmware, re.S).group(1)
        light = re.search(r"void setLightState\(bool on\) \{(.*?)\n\}", self.firmware, re.S).group(1)
        self.assertIn("PUMP_RELAY_PIN", pump)
        self.assertNotIn("LIGHT_RELAY_PIN", pump)
        self.assertIn("LIGHT_RELAY_PIN", light)
        self.assertNotIn("PUMP_RELAY_PIN", light)

    def test_safe_levels_are_loaded_before_output_mode(self):
        setup = self.firmware[self.firmware.index("void setup()") : self.firmware.index("void loop()")]
        self.assertLess(setup.index("digitalWrite(PUMP_RELAY_PIN"), setup.index("pinMode(PUMP_RELAY_PIN"))
        self.assertLess(setup.index("digitalWrite(LIGHT_RELAY_PIN"), setup.index("pinMode(LIGHT_RELAY_PIN"))
        timeout = self.firmware[self.firmware.index("DESLIGAMENTO DE SEGURANCA DA BOMBA") : self.firmware.index("runOfflineAutomation();")]
        self.assertIn("setPumpState(false)", timeout)
        self.assertNotIn("setLightState", timeout)


class RelayChannelAvailabilityTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="relay-owner@test.local", password="test")
        self.organization = Organization.objects.create(name="Relés", slug="relays")
        Membership.objects.create(user=self.owner, organization=self.organization, role=Membership.Role.OWNER)
        self.garden = Garden.objects.create(organization=self.organization, name="Horta", code="relay-garden")
        model = DeviceModel.objects.create(name="ESP8266", code="relay-esp")
        self.device = Device.objects.create(
            organization=self.organization, garden=self.garden, model=model,
            serial_number="RELAY-1", name="Controlador", last_seen_at=timezone.now(),
        )
        self.pump = self.device.channels.get(metric="pump_state")
        self.light = self.device.channels.get(metric="light_state")

    def test_uninstalled_light_is_hidden_and_cannot_receive_commands(self):
        snapshot = garden_snapshot(self.garden)
        self.assertIsNone(snapshot["light_channel"])
        self.assertIsNotNone(snapshot["pump_channel"])
        with self.assertRaises(ValueError):
            queue_actuator_command(user=self.owner, channel=self.light, action="on")

    def test_enabled_light_has_independent_command_and_state(self):
        self.light.is_enabled = True
        self.light.save(update_fields=["is_enabled", "updated_at"])
        snapshot = garden_snapshot(self.garden)
        self.assertEqual(snapshot["light_channel"], self.light)
        command = queue_actuator_command(user=self.owner, channel=self.light, action="on")
        self.assertEqual(command.channel.metric, "light_state")
        self.assertTrue(command.payload["on"])
        self.assertFalse(command.payload.get("pump", False))
        self.assertFalse(actuator_automation_summary(snapshot)["lighting"]["active"])
