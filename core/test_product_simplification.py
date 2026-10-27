from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from crops.models import Crop, Cultivar, PlantingCycle
from devices.models import Channel, Device, DeviceCommand, DeviceModel
from devices.services import queue_actuator_command
from gardens.configuration import effective_garden_configuration
from gardens.models import Garden, GardenModel, GardenModule, ModuleType


class ProductSimplificationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="owner@test.local", password="test", full_name="Cliente")
        self.other = User.objects.create_user(email="other@test.local", password="test", full_name="Outro")
        self.tech = User.objects.create_user(email="tech@test.local", password="test", full_name="Técnico", employee_role=User.EmployeeRole.TECHNICIAN)
        self.admin = User.objects.create_user(email="admin@test.local", password="test", full_name="Admin", employee_role=User.EmployeeRole.ADMIN)
        self.org = Organization.objects.create(name="Cliente", slug="cliente-test")
        self.other_org = Organization.objects.create(name="Outro", slug="outro-test")
        Membership.objects.create(user=self.owner, organization=self.org, role=Membership.Role.OWNER)
        Membership.objects.create(user=self.other, organization=self.other_org, role=Membership.Role.OWNER)
        self.model = GardenModel.objects.create(name="HortaViva P", code="hv-p", capacity=4, photos_per_day=4)
        self.garden = Garden.objects.create(organization=self.org, name="Horta", code="horta", garden_model=self.model, primary_technician=self.tech)
        device_model = DeviceModel.objects.create(name="ESP8266", code="esp-test")
        self.device = Device.objects.create(
            organization=self.org, garden=self.garden, model=device_model,
            serial_number="ESP-1", name="Controlador", status=Device.Status.ONLINE,
            last_seen_at=timezone.now(),
        )
        self.pump = Channel.objects.create(device=self.device, key="pump-test", name="Bomba", kind=Channel.Kind.ACTUATOR, metric="pump_state", value_type=Channel.ValueType.BOOLEAN)
        self.light = Channel.objects.create(device=self.device, key="light-test", name="Luz", kind=Channel.Kind.ACTUATOR, metric="light_state", value_type=Channel.ValueType.BOOLEAN)

    def test_model_camera_configuration_and_garden_reference(self):
        self.assertEqual(self.garden.garden_model, self.model)
        self.assertEqual(effective_garden_configuration(self.garden)["camera"]["photos_per_day"], 4)

    def test_actuator_scope_for_customer_technician_and_admin(self):
        self.assertEqual(queue_actuator_command(user=self.owner, channel=self.pump, action="irrigate").payload["duration_seconds"], 10)
        self.assertTrue(queue_actuator_command(user=self.tech, channel=self.light, action="on").payload["on"])
        self.assertFalse(queue_actuator_command(user=self.admin, channel=self.light, action="off").payload["on"])
        with self.assertRaises(PermissionDenied):
            queue_actuator_command(user=self.other, channel=self.pump, action="irrigate")

    def test_light_buttons_persist_set_state_commands(self):
        self.client.force_login(self.owner)
        url = reverse("device-action")

        response = self.client.post(url, {
            "channel": str(self.light.id), "action": "on", "next": reverse("customer-dashboard"),
        })
        self.assertEqual(response.status_code, 302)
        command = DeviceCommand.objects.get(channel=self.light)
        self.assertEqual(command.command_type, "set_state")
        self.assertEqual(command.payload["on"], True)

        response = self.client.post(url, {
            "channel": str(self.light.id), "action": "off", "next": reverse("customer-dashboard"),
        })
        self.assertEqual(response.status_code, 302)
        command = DeviceCommand.objects.filter(channel=self.light).latest("created_at")
        self.assertEqual(command.command_type, "set_state")
        self.assertEqual(command.payload["on"], False)

    def test_ajax_manual_command_is_immediately_available_and_reports_ack_state(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("device-action"),
            {"channel": str(self.light.id), "action": "on", "next": reverse("customer-dashboard")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 201)
        command = DeviceCommand.objects.get(id=response.json()["id"])
        self.assertEqual(command.status, DeviceCommand.Status.PENDING)
        self.assertEqual(response.json()["status_url"], reverse("device-command-status", args=[command.id]))

        command.status = DeviceCommand.Status.SUCCEEDED
        command.result = {"relay": True}
        command.acknowledged_at = timezone.now()
        command.save(update_fields=["status", "result", "acknowledged_at"])
        status = self.client.get(response.json()["status_url"])
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "succeeded")
        self.assertIs(status.json()["state"], True)

    def test_identical_pending_manual_command_is_deduplicated(self):
        self.client.force_login(self.owner)
        request_data = {
            "channel": str(self.light.id), "action": "on",
            "next": reverse("customer-dashboard"),
        }
        headers = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest", "HTTP_ACCEPT": "application/json"}
        first = self.client.post(reverse("device-action"), request_data, **headers)
        second = self.client.post(reverse("device-action"), request_data, **headers)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(
            DeviceCommand.objects.filter(
                channel=self.light,
                status__in=[DeviceCommand.Status.PENDING, DeviceCommand.Status.DELIVERED],
                payload__on=True,
            ).count(),
            1,
        )
        self.assertIn("app;dur=", second.headers["Server-Timing"])

    def test_opposite_state_is_not_deduplicated(self):
        first = queue_actuator_command(user=self.owner, channel=self.light, action="on")
        second = queue_actuator_command(user=self.owner, channel=self.light, action="off")
        self.assertNotEqual(first.id, second.id)

    def test_ack_status_supports_light_and_pump_on_and_off(self):
        self.client.force_login(self.owner)
        for channel in (self.light, self.pump):
            for state in (True, False):
                command = DeviceCommand.objects.create(
                    device=self.device, channel=channel, command_type="set_state",
                    payload={"on": state}, idempotency_key=f"ui:{channel.id}:{state}",
                    status=DeviceCommand.Status.SUCCEEDED, result={"relay": state},
                    acknowledged_at=timezone.now(),
                )
                response = self.client.get(reverse("device-command-status", args=[command.id]))
                self.assertEqual(response.status_code, 200)
                self.assertIs(response.json()["state"], state)

    def test_employee_admin_has_global_advanced_access(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("ops-collection", args=["telemetry"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("garden-detail", args=[self.garden.pk])).status_code, 200)

    def test_missing_light_channel_is_not_created(self):
        self.light.delete()
        before = Channel.objects.filter(device=self.device, metric="light_state").count()
        effective_garden_configuration(self.garden)
        self.assertEqual(Channel.objects.filter(device=self.device, metric="light_state").count(), before)

    def test_multiple_incompatible_crops_require_confirmation(self):
        module_type = ModuleType.objects.create(name="Vaso", code="vaso-test")
        for position, (code, duration) in enumerate((("crop-a", 10), ("crop-b", 20)), 1):
            crop = Crop.objects.create(common_name=code, code=code, pump_duration_seconds=duration)
            cultivar = Cultivar.objects.create(crop=crop, name="Comum")
            module = GardenModule.objects.create(organization=self.org, module_type=module_type, serial_number=f"M-{position}", name=f"Posição {position}", position_label=str(position))
            PlantingCycle.objects.create(organization=self.org, garden=self.garden, module=module, crop=crop, cultivar=cultivar, status=PlantingCycle.Status.ACTIVE, planted_at=timezone.now())
        config = effective_garden_configuration(self.garden)
        self.assertTrue(config["requires_confirmation"])
        self.assertNotIn("irrigation", config)
