import re
from datetime import timedelta
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Channel, Device, DeviceCommand, DeviceHeartbeat, DeviceModel, TelemetryReading
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
        cls.local_firmware = (
            Path(__file__).resolve().parents[1]
            / "firmware" / "horta_inteligente_local" / "horta_inteligente_local.ino"
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

    def test_actuator_states_are_reported_and_timer_marks_pump_off(self):
        telemetry = self.firmware[self.firmware.index("void sendTelemetry()") : self.firmware.index("void sendHeartbeat()")]
        self.assertIn('pumpItem["channel"] = "pump"', telemetry)
        self.assertIn('pumpItem["value"] = pumpRelayOn', telemetry)
        self.assertIn('lightItem["channel"] = "grow-light"', telemetry)
        self.assertIn('lightItem["value"] = lightRelayOn', telemetry)
        timeout = self.firmware[self.firmware.index("DESLIGAMENTO DE SEGURANCA DA BOMBA") : self.firmware.index("runOfflineAutomation();")]
        self.assertIn("setPumpState(false)", timeout)
        self.assertNotIn("setLightState", timeout)

    def test_pump_has_async_cutoff_and_duplicate_protection(self):
        for name, firmware in (("platformio", self.firmware), ("arduino", self.local_firmware)):
            with self.subTest(firmware=name):
                self.assertIn("#include <Ticker.h>", firmware)
                self.assertIn("forcePumpOffFromTimer", firmware)
                self.assertIn("armPumpSafetyTimer", firmware)
                self.assertIn("pumpSafetyTimer.once_ms", firmware)
                self.assertIn("PUMP_RELAY_ACTIVE_LOW ? HIGH : LOW", firmware)
                self.assertIn("EXECUTED_COMMAND_CACHE_SIZE", firmware)

    def test_every_pump_start_is_locally_time_limited(self):
        pump_commands = self.local_firmware[
            self.local_firmware.index("// BOMBA", self.local_firmware.index("void pollCommands()")):
            self.local_firmware.index("// LAMPADA", self.local_firmware.index("void pollCommands()"))
        ]
        self.assertNotIn("Ligada manualmente sem temporizador", pump_commands)
        self.assertIn("armPumpSafetyTimer(durationSeconds)", self.local_firmware)
        self.assertIn("armPumpSafetyTimer(duration)", self.local_firmware)
        self.assertIn("armPumpSafetyTimer(durationSeconds)", self.firmware)
        self.assertIn("armPumpSafetyTimer(duration)", self.firmware)


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
        self.light.is_enabled = False
        self.light.save(update_fields=["is_enabled", "updated_at"])
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

    def test_crossed_canonical_channels_are_rejected(self):
        self.light.metric = "pump_state"
        self.light.save(update_fields=["metric", "updated_at"])
        with self.assertRaisesRegex(ValueError, "canal de atuador inconsistente"):
            queue_actuator_command(user=self.owner, channel=self.light, action="on")

    def test_snapshot_rejects_multiple_controllers_instead_of_mixing_them(self):
        second = Device.objects.create(
            organization=self.organization, garden=self.garden, model=self.device.model,
            serial_number="RELAY-2", name="Controlador duplicado",
            kind=Device.Kind.CONTROLLER, last_seen_at=timezone.now(),
        )
        second.channels.filter(key="grow-light").update(is_enabled=True)

        snapshot = garden_snapshot(self.garden)

        self.assertIsNone(snapshot["controller"])
        self.assertIsNone(snapshot["pump_channel"])
        self.assertIsNone(snapshot["light_channel"])

    def test_customer_ui_distinguishes_installed_from_uninstalled_light(self):
        self.client.force_login(self.owner)

        installed = self.client.get(reverse("customer-dashboard"))
        self.assertContains(installed, "Estado não confirmado")
        self.assertNotContains(installed, "Hardware não instalado")

        self.light.is_enabled = False
        self.light.save(update_fields=["is_enabled", "updated_at"])
        uninstalled = self.client.get(reverse("customer-dashboard"))
        self.assertContains(uninstalled, "Canal de iluminação indisponível")

    def _enable_light(self):
        self.light.is_enabled = True
        self.light.save(update_fields=["is_enabled", "updated_at"])

    def _summary(self):
        return actuator_automation_summary(garden_snapshot(self.garden))

    def test_requested_command_does_not_become_confirmed_state(self):
        self._enable_light()
        queue_actuator_command(user=self.owner, channel=self.light, action="on")

        lighting = self._summary()["lighting"]

        self.assertIsNone(lighting["state"])
        self.assertTrue(lighting["updating"])

    def test_confirmed_pump_and_light_states_are_independent(self):
        self._enable_light()
        now = timezone.now()
        TelemetryReading.objects.create(
            channel=self.pump, recorded_at=now, boolean_value=True, idempotency_key="pump-on"
        )
        TelemetryReading.objects.create(
            channel=self.light, recorded_at=now, boolean_value=False, idempotency_key="light-off"
        )

        summary = self._summary()

        self.assertIs(summary["irrigation"]["state"], True)
        self.assertIs(summary["lighting"]["state"], False)
        self.assertEqual(summary["irrigation"]["confirmed_at"], now)
        self.assertEqual(summary["lighting"]["confirmed_at"], now)

    def test_new_confirmation_replaces_each_state_without_cross_talk(self):
        self._enable_light()
        now = timezone.now()
        TelemetryReading.objects.create(
            channel=self.pump, recorded_at=now, boolean_value=False, idempotency_key="pump-off"
        )
        TelemetryReading.objects.create(
            channel=self.light, recorded_at=now, boolean_value=True, idempotency_key="light-on"
        )

        summary = self._summary()

        self.assertIs(summary["irrigation"]["state"], False)
        self.assertIs(summary["lighting"]["state"], True)

    def test_expired_command_keeps_last_confirmed_state_and_reports_failure(self):
        self._enable_light()
        confirmed_at = timezone.now() - timedelta(minutes=1)
        TelemetryReading.objects.create(
            channel=self.light, recorded_at=confirmed_at, boolean_value=False,
            idempotency_key="confirmed-light-off",
        )
        DeviceCommand.objects.create(
            device=self.device, channel=self.light, command_type="set_state", payload={"on": True},
            status=DeviceCommand.Status.EXPIRED, expires_at=timezone.now() - timedelta(seconds=1),
            idempotency_key="expired-light-on",
        )

        lighting = self._summary()["lighting"]

        self.assertIs(lighting["state"], False)
        self.assertFalse(lighting["updating"])
        self.assertTrue(lighting["confirmation_failed"])

    def test_heartbeat_accepts_canonical_and_legacy_diagnostic_names(self):
        self._enable_light()
        now = timezone.now()
        DeviceHeartbeat.objects.create(
            device=self.device, recorded_at=now,
            diagnostics={"relay_pump_on": True, "relay_light_on": True},
        )

        summary = self._summary()

        self.assertIs(summary["irrigation"]["state"], True)
        self.assertIs(summary["lighting"]["state"], True)
        self.assertEqual(summary["lighting"]["confirmed_at"], now)
