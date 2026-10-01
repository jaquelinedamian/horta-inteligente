from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Device, DeviceModel, GardenPhoto
from gardens.access import gardens_for_user
from .models import Garden


class GardenAccessTests(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Cliente A", slug="cliente-a")
        self.org_b = Organization.objects.create(name="Cliente B", slug="cliente-b")
        self.garden_a = Garden.objects.create(organization=self.org_a, name="Horta A", code="a")
        self.garden_b = Garden.objects.create(organization=self.org_b, name="Horta B", code="b")
        self.client_user = User.objects.create_user(email="a@example.test", password="test-pass", full_name="A")
        Membership.objects.create(user=self.client_user, organization=self.org_a, role=Membership.Role.OWNER)
        self.tech = User.objects.create_user(email="tech@example.test", password="test-pass", full_name="Técnico")
        Membership.objects.create(user=self.tech, organization=self.org_a, role=Membership.Role.TECHNICIAN)
        self.garden_a.primary_technician = self.tech
        self.garden_a.save(update_fields=["primary_technician"])
        self.admin = User.objects.create_superuser(email="admin@example.test", password="test-pass")

    def test_customer_only_sees_own_garden(self):
        self.assertQuerySetEqual(gardens_for_user(self.client_user), [self.garden_a], transform=lambda item: item)

    def test_technician_only_sees_assigned_garden(self):
        self.assertQuerySetEqual(gardens_for_user(self.tech), [self.garden_a], transform=lambda item: item)

    def test_admin_sees_all_gardens(self):
        self.assertEqual(gardens_for_user(self.admin).count(), 2)

    def test_garden_detail_revalidates_object_scope(self):
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse("garden-detail", args=[self.garden_a.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("garden-detail", args=[self.garden_b.id])).status_code, 404)
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse("garden-detail", args=[self.garden_b.id])).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("garden-detail", args=[self.garden_b.id])).status_code, 200)

    def test_customer_cannot_view_photo_from_another_garden(self):
        model = DeviceModel.objects.create(name="ESP32-CAM", code="access-camera", hardware_platform="ESP32")
        camera = Device.objects.create(
            organization=self.org_b, garden=self.garden_b, model=model,
            serial_number="CAM-B", name="Camera B", kind=Device.Kind.CAMERA,
        )
        photo = GardenPhoto.objects.create(
            garden=self.garden_b, device=camera, captured_at=timezone.now(),
            image_data=b"\xff\xd8jpeg\xff\xd9", content_type="image/jpeg", byte_size=10,
        )
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(reverse("garden-photo", args=[photo.id])).status_code, 404)
