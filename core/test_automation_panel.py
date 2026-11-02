from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import (
    Channel, Device, DeviceCommand, DeviceModel, IrrigationSchedule, LightingSchedule,
    TelemetryReading,
)
from gardens.models import Garden

from .automation import _schedule_events, format_weekdays


class SharedAutomationPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Painel", slug="painel-automacao")
        cls.owner = User.objects.create_user(email="owner-panel@test.local", password="test")
        cls.viewer = User.objects.create_user(email="viewer-panel@test.local", password="test")
        cls.tech = User.objects.create_user(
            email="tech-panel@test.local", password="test", employee_role=User.EmployeeRole.TECHNICIAN
        )
        cls.admin = User.objects.create_user(
            email="admin-panel@test.local", password="test", employee_role=User.EmployeeRole.ADMIN
        )
        Membership.objects.create(user=cls.owner, organization=cls.org, role=Membership.Role.OWNER)
        Membership.objects.create(user=cls.viewer, organization=cls.org, role=Membership.Role.VIEWER)
        cls.garden = Garden.objects.create(
            organization=cls.org, name="Horta painel", code="horta-painel",
            primary_technician=cls.tech,
        )
        model = DeviceModel.objects.create(name="ESP8266 painel", code="esp-panel")
        cls.device = Device.objects.create(
            organization=cls.org, garden=cls.garden, model=model,
            serial_number="ESP-PANEL", name="Controlador", kind=Device.Kind.CONTROLLER,
            status=Device.Status.ONLINE, last_seen_at=timezone.now(),
        )
        cls.pump = cls.device.channels.get(key="pump")
        cls.light = cls.device.channels.get(key="grow-light")
        cls.light.is_enabled = True
        cls.light.save(update_fields=["is_enabled", "updated_at"])
        IrrigationSchedule.objects.create(
            actuator=cls.pump, start_time=time(7), duration_seconds=10,
            days_of_week=[0, 1, 2, 3, 4], enabled=True,
        )
        IrrigationSchedule.objects.create(
            actuator=cls.pump, start_time=time(6), duration_seconds=99,
            days_of_week=[5, 6], enabled=False,
        )
        LightingSchedule.objects.create(
            actuator=cls.light, name="Manhã", start_time=time(6), end_time=time(10),
            days_of_week=list(range(7)), enabled=True,
        )
        TelemetryReading.objects.create(
            channel=cls.pump, recorded_at=timezone.now(), boolean_value=False,
            idempotency_key="pump-panel",
        )
        TelemetryReading.objects.create(
            channel=cls.light, recorded_at=timezone.now(), boolean_value=True,
            idempotency_key="light-panel",
        )

    def test_weekday_formatter_has_shared_friendly_ranges(self):
        self.assertEqual(format_weekdays(range(7)), "Todos os dias")
        self.assertEqual(format_weekdays(range(5)), "Seg–Sex")
        self.assertEqual(format_weekdays([5, 6]), "Sáb–Dom")
        self.assertEqual(format_weekdays([0, 2, 4]), "Seg, Qua, Sex")

    def test_next_event_respects_schedule_timezone(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=ZoneInfo("UTC"))
        with patch("core.automation.timezone.now", return_value=now):
            event = _schedule_events([
                {"time": "10:00", "days": [0], "timezone": "America/Sao_Paulo"}
            ], event_fields=(("time", ""),))
        self.assertEqual(event[0].astimezone(ZoneInfo("America/Sao_Paulo")).strftime("%H:%M"), "10:00")

    def test_owner_view_uses_confirmed_state_schedule_and_controls(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("customer-dashboard"))
        self.assertContains(response, "Bomba desligada")
        self.assertContains(response, "Luz ligada")
        self.assertContains(response, "07:00 · Seg–Sex")
        self.assertNotContains(response, "99 s")
        self.assertContains(response, "Irrigar agora")
        self.assertContains(response, "Configuração de irrigação")
        self.assertContains(response, f'name="channel" value="{self.pump.id}"', count=1)
        self.assertContains(response, 'data-action="irrigate" data-channel="pump"')
        self.assertContains(response, f'name="channel" value="{self.light.id}"', count=1)
        self.assertContains(response, 'data-action="on" data-channel="grow-light"')
        self.assertContains(response, 'data-action="off" data-channel="grow-light"')

    def test_confirmed_false_telemetry_displays_light_off(self):
        TelemetryReading.objects.create(
            channel=self.light, recorded_at=timezone.now() + timedelta(seconds=1),
            boolean_value=False, idempotency_key="light-panel-off",
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("customer-dashboard"))
        self.assertContains(response, "Luz desligada")

    def test_stale_light_telemetry_displays_unconfirmed_state(self):
        self.light.readings.all().delete()
        TelemetryReading.objects.create(
            channel=self.light, recorded_at=timezone.now() - timedelta(hours=3),
            boolean_value=True, idempotency_key="light-panel-stale",
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("customer-dashboard"))
        self.assertContains(response, "Estado não confirmado")

    def test_pending_light_command_keeps_last_confirmed_state_visible(self):
        DeviceCommand.objects.create(
            device=self.device, channel=self.light, command_type="set_state",
            payload={"on": False}, idempotency_key="pending-light-panel",
            status=DeviceCommand.Status.PENDING,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("customer-dashboard"))
        self.assertContains(response, "Luz ligada")
        self.assertContains(response, "Aguardando confirmação de novo comando")

    def test_mismatched_channels_do_not_render_crossed_action_buttons(self):
        self.pump.metric = "light_state"
        self.pump.save(update_fields=["metric", "updated_at"])
        self.client.force_login(self.owner)
        response = self.client.get(reverse("customer-dashboard"))
        self.assertContains(response, "Canal de irrigação indisponível")
        self.assertNotContains(response, 'data-action="irrigate" data-channel="pump"')

    def test_viewer_sees_panel_without_operational_or_configuration_controls(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("customer-dashboard"))
        self.assertContains(response, "Automação e comandos manuais")
        self.assertContains(response, "acesso somente para consulta")
        self.assertNotContains(response, 'name="action" value="irrigate"')
        self.assertNotContains(response, "Configuração de irrigação")

    def test_technician_and_admin_use_the_same_shared_panel(self):
        self.client.force_login(self.tech)
        technician = self.client.get(reverse("garden-detail", args=[self.garden.pk]))
        self.assertIn("components/garden_automation_panel.html", [item.name for item in technician.templates])
        self.assertContains(technician, "07:00 · Seg–Sex")
        self.assertContains(technician, "Configuração de iluminação")

        self.client.force_login(self.admin)
        admin = self.client.get(
            f"{reverse('ops-client-detail', args=[self.owner.pk])}?aba=gardens"
        )
        self.assertIn("components/garden_automation_panel.html", [item.name for item in admin.templates])
        self.assertContains(admin, "07:00 · Seg–Sex")
        self.assertContains(admin, "Configuração de iluminação")

    def test_quick_irrigation_update_persists_and_returns_to_current_view(self):
        self.client.force_login(self.owner)
        schedule = self.pump.irrigation_schedules.filter(enabled=True).get()
        response = self.client.post(reverse("garden-automation-update", args=[self.garden.pk]), {
            "action": "irrigation_update", "schedule_id": schedule.pk,
            "start_time": "08:30", "duration_seconds": "15",
            "days_of_week": ["5", "6"], "enabled": "on", "next": reverse("customer-dashboard"),
        })
        self.assertRedirects(response, reverse("customer-dashboard"), fetch_redirect_response=False)
        schedule.refresh_from_db()
        self.assertEqual(schedule.start_time, time(8, 30))
        self.assertEqual(schedule.duration_seconds, 15)
        self.assertEqual(schedule.days_of_week, [5, 6])
