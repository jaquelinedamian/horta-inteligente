from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Device, DeviceModel, GardenPhoto
from gardens.models import Garden


class CameraColorCalibrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="color-admin@test.local", password="test",
            employee_role=User.EmployeeRole.ADMIN,
        )
        cls.technician = User.objects.create_user(
            email="color-tech@test.local", password="test",
            employee_role=User.EmployeeRole.TECHNICIAN,
        )
        cls.customer = User.objects.create_user(email="color-customer@test.local", password="test")
        cls.organization = Organization.objects.create(name="Cores", slug="cores-camera")
        Membership.objects.create(
            user=cls.customer, organization=cls.organization, role=Membership.Role.OWNER,
        )
        cls.garden = Garden.objects.create(
            organization=cls.organization, name="Horta cores", code="horta-cores",
        )
        model = DeviceModel.objects.create(name="ESP32-CAM cores", code="esp32-cam-cores")
        cls.camera = Device.objects.create(
            organization=cls.organization, garden=cls.garden, model=model,
            serial_number="CAM-COLOR-1", name="Câmera cores", kind=Device.Kind.CAMERA,
            local_ip="192.168.1.42", metadata={"installation": {"position": "frontal"}},
        )
        cls.photo = GardenPhoto.objects.create(
            garden=cls.garden, device=cls.camera, captured_at=timezone.now(),
            image_data=b"original-jpeg-bytes", content_type="image/jpeg", byte_size=19,
        )

    @property
    def url(self):
        return reverse("ops-camera-color-calibration", args=[self.camera.pk])

    def test_only_admin_can_open_color_calibration(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Calibração de cores")
        self.assertContains(response, "Somente administração")

        for user in (self.technician, self.customer):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_calibration_link_is_hidden_from_technician(self):
        client_url = reverse("ops-client-detail", args=[self.customer.pk]) + "?aba=gardens"
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(client_url), self.url)
        self.client.force_login(self.technician)
        self.assertNotContains(self.client.get(client_url), self.url)

    def test_profile_persists_per_camera_without_overwriting_metadata_or_photo(self):
        original = bytes(self.photo.image_data)
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {
            "action": "save", "mode": "manual", "temperature": "-20", "hue": "12",
            "saturation": "90", "contrast": "110", "brightness": "98",
            "green_intensity": "104", "magenta_compensation": "35", "white_balance": "on",
        })
        self.assertRedirects(response, self.url)
        self.camera.refresh_from_db()
        profile = self.camera.metadata["color_calibration"]
        self.assertEqual(profile["mode"], "manual")
        self.assertEqual(profile["magenta_compensation"], 35)
        self.assertTrue(profile["white_balance"])
        self.assertEqual(self.camera.metadata["installation"], {"position": "frontal"})
        self.photo.refresh_from_db()
        self.assertEqual(bytes(self.photo.image_data), original)

    def test_restore_returns_to_original_defaults(self):
        self.camera.metadata = {"color_calibration": {"mode": "manual", "hue": 50}}
        self.camera.save(update_fields=["metadata", "updated_at"])
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"action": "reset"})
        self.assertRedirects(response, self.url)
        self.camera.refresh_from_db()
        profile = self.camera.metadata["color_calibration"]
        self.assertEqual(profile["mode"], "original")
        self.assertEqual(profile["hue"], 0)
        self.assertEqual(profile["saturation"], 100)

    def test_admin_preview_keeps_original_photo_and_supports_live_stream(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        photo_url = reverse("garden-photo", args=[self.photo.pk])
        self.assertContains(response, photo_url, count=2)
        self.assertContains(response, "http://192.168.1.42/stream")
        self.assertContains(response, "Imagem corrigida digitalmente")
