from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Device, DeviceModel, GardenPhoto
from gardens.models import Garden


class CustomerLiveCameraTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email="camera-owner@test.local", password="test")
        self.other_owner = User.objects.create_user(email="camera-other@test.local", password="test")
        self.organization = Organization.objects.create(name="Cliente câmera", slug="cliente-camera")
        self.other_organization = Organization.objects.create(name="Outro cliente", slug="outro-camera")
        Membership.objects.create(
            user=self.owner, organization=self.organization, role=Membership.Role.OWNER
        )
        Membership.objects.create(
            user=self.other_owner,
            organization=self.other_organization,
            role=Membership.Role.OWNER,
        )
        self.garden = Garden.objects.create(
            organization=self.organization, name="Módulo P", code="modulo-p"
        )
        self.other_garden = Garden.objects.create(
            organization=self.other_organization, name="Horta externa", code="externa-camera"
        )
        model = DeviceModel.objects.create(name="ESP32-CAM", code="live-camera")
        self.camera = Device.objects.create(
            organization=self.organization,
            garden=self.garden,
            model=model,
            serial_number="LIVE-CAM-1",
            name="Câmera Módulo P",
            kind=Device.Kind.CAMERA,
            status=Device.Status.ONLINE,
            last_seen_at=timezone.now(),
            local_ip="192.168.15.20",
        )
        self.other_camera = Device.objects.create(
            organization=self.other_organization,
            garden=self.other_garden,
            model=model,
            serial_number="LIVE-CAM-2",
            name="Câmera externa",
            kind=Device.Kind.CAMERA,
            status=Device.Status.ONLINE,
            last_seen_at=timezone.now(),
            local_ip="192.168.99.20",
        )
        self.client.force_login(self.owner)

    def stream_info_url(self, garden=None):
        return reverse("garden-camera-stream-info", args=[(garden or self.garden).pk])

    def test_dashboard_renders_live_modal_without_camera_address_or_credentials(self):
        response = self.client.get(reverse("customer-dashboard"))

        self.assertContains(response, "Ver câmera ao vivo")
        self.assertContains(response, 'id="liveCameraModal"')
        self.assertContains(response, self.stream_info_url())
        self.assertNotContains(response, "http://192.168.15.20/stream")
        self.assertNotContains(response, "/capture")

    def test_stream_info_returns_mjpeg_lan_url_without_creating_photo(self):
        photo_count = GardenPhoto.objects.count()

        response = self.client.get(self.stream_info_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response.json()["stream_url"], "http://192.168.15.20/stream")
        self.assertEqual(response.json()["garden_name"], "Módulo P")
        self.assertEqual(GardenPhoto.objects.count(), photo_count)

    def test_customer_cannot_request_another_organizations_camera(self):
        response = self.client.get(self.stream_info_url(self.other_garden))

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "192.168.99.20", status_code=404)

    def test_offline_camera_disables_button_and_stream_info(self):
        self.camera.last_seen_at = timezone.now() - timedelta(hours=1)
        self.camera.save(update_fields=["last_seen_at", "updated_at"])

        dashboard = self.client.get(reverse("customer-dashboard"))
        stream_info = self.client.get(self.stream_info_url())

        self.assertContains(dashboard, "Câmera indisponível")
        self.assertNotContains(dashboard, "Ver câmera ao vivo")
        self.assertEqual(stream_info.status_code, 503)
        self.assertFalse(stream_info.json()["available"])

    def test_online_camera_without_local_ip_reports_unavailable(self):
        self.camera.local_ip = None
        self.camera.save(update_fields=["local_ip", "updated_at"])

        response = self.client.get(self.stream_info_url())

        self.assertEqual(response.status_code, 503)
        self.assertIn("endereço local", response.json()["message"])
