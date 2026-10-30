import json
from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Device, DeviceCommand, DeviceCredential, DeviceModel, GardenPhoto
from gardens.models import Garden


class ManualCameraCaptureTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="capture-owner@test.local", password="test")
        self.other = User.objects.create_user(email="capture-other@test.local", password="test")
        self.tech = User.objects.create_user(email="capture-tech@test.local", password="test", employee_role=User.EmployeeRole.TECHNICIAN)
        self.unassigned_tech = User.objects.create_user(email="capture-tech-other@test.local", password="test", employee_role=User.EmployeeRole.TECHNICIAN)
        self.admin = User.objects.create_user(email="capture-admin@test.local", password="test", employee_role=User.EmployeeRole.ADMIN)
        self.organization = Organization.objects.create(name="Captura", slug="captura")
        self.other_organization = Organization.objects.create(name="Outra", slug="captura-outra")
        Membership.objects.create(user=self.owner, organization=self.organization, role=Membership.Role.OWNER)
        Membership.objects.create(user=self.other, organization=self.other_organization, role=Membership.Role.OWNER)
        self.garden = Garden.objects.create(organization=self.organization, name="Horta", code="capture", primary_technician=self.tech)
        self.other_garden = Garden.objects.create(organization=self.other_organization, name="Outra", code="capture-other")
        model = DeviceModel.objects.create(name="ESP32-CAM", code="capture-camera")
        now = timezone.now()
        self.camera = Device.objects.create(
            organization=self.organization, garden=self.garden, model=model, serial_number="CAPTURE-1",
            name="Câmera", kind=Device.Kind.CAMERA, status=Device.Status.ONLINE, last_seen_at=now,
        )
        self.other_camera = Device.objects.create(
            organization=self.other_organization, garden=self.other_garden, model=model, serial_number="CAPTURE-2",
            name="Outra câmera", kind=Device.Kind.CAMERA, status=Device.Status.ONLINE, last_seen_at=now,
        )

    def capture_url(self, garden=None):
        return reverse("garden-capture-photo", args=[(garden or self.garden).pk])

    def test_owner_can_queue_capture_for_own_garden_but_not_another(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.capture_url()).status_code, 302)
        command = DeviceCommand.objects.get(device=self.camera)
        self.assertEqual(command.command_type, "capture_photo")
        self.assertEqual(command.payload["source"], "manual")
        self.assertEqual(self.client.post(self.capture_url(self.other_garden)).status_code, 404)
        self.assertFalse(DeviceCommand.objects.filter(device=self.other_camera).exists())

    def test_assigned_technician_can_capture_and_unassigned_cannot(self):
        self.client.force_login(self.tech)
        self.assertEqual(self.client.post(self.capture_url()).status_code, 302)
        DeviceCommand.objects.all().delete()
        self.client.force_login(self.unassigned_tech)
        self.assertEqual(self.client.post(self.capture_url()).status_code, 404)
        self.assertFalse(DeviceCommand.objects.exists())

    def test_admin_can_capture(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.capture_url()).status_code, 302)
        self.assertTrue(DeviceCommand.objects.filter(device=self.camera, command_type="capture_photo").exists())

    def test_admin_card_shows_capture_only_for_linked_camera_and_disables_it_offline(self):
        self.client.force_login(self.admin)
        url = f"{reverse('ops-client-detail', args=[self.owner.pk])}?aba=gardens"
        response = self.client.get(url)
        self.assertContains(response, "Tirar foto")
        self.assertContains(response, self.capture_url())
        self.camera.last_seen_at = timezone.now() - timedelta(hours=1)
        self.camera.save(update_fields=["last_seen_at", "updated_at"])
        response = self.client.get(url)
        self.assertContains(response, 'disabled title="Câmera offline"')
        self.camera.delete()
        response = self.client.get(url)
        self.assertNotContains(response, "Tirar foto")

    def test_offline_or_missing_camera_does_not_create_command(self):
        self.client.force_login(self.owner)
        self.camera.last_seen_at = timezone.now() - timedelta(hours=1)
        self.camera.save(update_fields=["last_seen_at", "updated_at"])
        self.client.post(self.capture_url())
        self.assertFalse(DeviceCommand.objects.exists())
        self.camera.delete()
        self.client.post(self.capture_url())
        self.assertFalse(DeviceCommand.objects.exists())

    def test_pending_command_and_cooldown_are_deduplicated(self):
        self.client.force_login(self.owner)
        self.client.post(self.capture_url())
        first = DeviceCommand.objects.get()
        self.client.post(self.capture_url())
        self.assertEqual(DeviceCommand.objects.count(), 1)
        first.status = DeviceCommand.Status.SUCCEEDED
        first.save(update_fields=["status", "updated_at"])
        self.client.post(self.capture_url())
        self.assertEqual(DeviceCommand.objects.count(), 1)

    def test_capture_requires_post_and_csrf(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.capture_url()).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(csrf_client.post(self.capture_url()).status_code, 403)

    def test_manual_upload_becomes_latest_photo(self):
        old = GardenPhoto.objects.create(
            garden=self.garden, device=self.camera, captured_at=timezone.now() - timedelta(minutes=1),
            image_data=b"\xff\xd8old\xff\xd9", byte_size=7,
        )
        _, token = DeviceCredential.issue(self.camera)
        response = self.client.post(
            reverse("device_api:photo"), b"\xff\xd8manual\xff\xd9", content_type="image/jpeg",
            HTTP_AUTHORIZATION=f"Device {token}", HTTP_X_DEVICE_ID=str(self.camera.pk),
            HTTP_X_CAPTURE_ORIGIN="manual",
        )
        self.assertEqual(response.status_code, 201)
        latest = GardenPhoto.objects.filter(garden=self.garden).first()
        self.assertNotEqual(latest.pk, old.pk)
        self.assertEqual(latest.source, GardenPhoto.Source.MANUAL)
