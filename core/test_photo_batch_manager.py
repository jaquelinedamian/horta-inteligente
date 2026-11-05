from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Organization, User
from devices.models import Device, DeviceModel, GardenPhoto
from gardens.models import Garden


class PhotoBatchManagerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="photo-admin@test.local", password="test", employee_role=User.EmployeeRole.ADMIN,
        )
        cls.technician = User.objects.create_user(
            email="photo-tech@test.local", password="test", employee_role=User.EmployeeRole.TECHNICIAN,
        )
        cls.customer = User.objects.create_user(email="photo-customer@test.local", password="test")
        cls.organization = Organization.objects.create(name="Fotos", slug="fotos-lote")
        Membership.objects.create(user=cls.customer, organization=cls.organization, role=Membership.Role.OWNER)
        cls.garden = Garden.objects.create(organization=cls.organization, name="Horta A", code="foto-a")
        cls.other_garden = Garden.objects.create(organization=cls.organization, name="Horta B", code="foto-b")
        model = DeviceModel.objects.create(name="ESP32 Fotos", code="esp32-fotos")
        cls.camera = Device.objects.create(
            organization=cls.organization, garden=cls.garden, model=model,
            serial_number="PHOTO-CAM-A", name="Câmera A", kind=Device.Kind.CAMERA,
        )
        cls.other_camera = Device.objects.create(
            organization=cls.organization, garden=cls.other_garden, model=model,
            serial_number="PHOTO-CAM-B", name="Câmera B", kind=Device.Kind.CAMERA,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    @property
    def url(self):
        return reverse("ops-photo-batch-manager")

    def photo(self, *, garden=None, camera=None, age_days=0):
        return GardenPhoto.objects.create(
            garden=garden or self.garden, device=camera or self.camera,
            captured_at=timezone.now() - timedelta(days=age_days),
            image_data=b"jpeg-test", content_type="image/jpeg", byte_size=9,
        )

    def post_selected(self, photos, **extra):
        data = {
            "selection_scope": "selected", "photo_ids": [str(item.pk) for item in photos],
            "period": "all", "return_query": "period=all",
        }
        data.update(extra)
        return self.client.post(self.url, data, follow=True)

    def test_deletes_one_photo_and_refreshes_gallery(self):
        selected = self.photo()
        response = self.post_selected([selected])
        self.assertFalse(GardenPhoto.objects.filter(pk=selected.pk).exists())
        self.assertContains(response, "Fotografias excluídas: 1. Falhas: 0.")
        self.assertNotContains(response, str(selected.pk))

    def test_deletes_multiple_and_preserves_unselected_photo(self):
        selected = [self.photo(), self.photo()]
        retained = self.photo()
        response = self.post_selected(selected)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GardenPhoto.objects.filter(pk__in=[item.pk for item in selected]).exists())
        self.assertTrue(GardenPhoto.objects.filter(pk=retained.pk).exists())

    def test_delete_all_filtered_only_affects_matching_garden_and_period(self):
        matching = self.photo()
        old = self.photo(age_days=40)
        other = self.photo(garden=self.other_garden, camera=self.other_camera)
        response = self.client.post(self.url, {
            "selection_scope": "filtered", "garden": str(self.garden.pk),
            "period": "30d", "return_query": f"garden={self.garden.pk}&period=30d",
        }, follow=True)
        self.assertContains(response, "Fotografias excluídas: 1")
        self.assertFalse(GardenPhoto.objects.filter(pk=matching.pk).exists())
        self.assertEqual(GardenPhoto.objects.filter(pk__in=[old.pk, other.pk]).count(), 2)

    def test_selection_can_include_ids_from_different_pages(self):
        photos = [self.photo() for _ in range(26)]
        first_page = self.client.get(self.url + "?period=all&page=1")
        second_page = self.client.get(self.url + "?period=all&page=2")
        self.assertEqual(first_page.context["photos"].paginator.num_pages, 2)
        self.assertContains(second_page, str(photos[0].pk))
        response = self.post_selected([photos[0], photos[-1]])
        self.assertContains(response, "Fotografias excluídas: 2")

    def test_technician_and_customer_cannot_access_or_delete(self):
        photo = self.photo()
        for user in (self.technician, self.customer):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, {
                "selection_scope": "selected", "photo_ids": [str(photo.pk)], "period": "all",
            }).status_code, 403)
        self.assertTrue(GardenPhoto.objects.filter(pk=photo.pk).exists())

    def test_invalid_or_missing_id_cancels_entire_operation(self):
        photo = self.photo()
        response = self.client.post(self.url, {
            "selection_scope": "selected", "photo_ids": [str(photo.pk), str(uuid4())],
            "period": "all",
        }, follow=True)
        self.assertContains(response, "Nenhuma imagem foi excluída")
        self.assertTrue(GardenPhoto.objects.filter(pk=photo.pk).exists())

    def test_storage_failure_rolls_back_without_partial_deletion(self):
        photos = [self.photo(), self.photo()]
        with patch("django.db.models.query.QuerySet.delete", side_effect=OSError("storage unavailable")):
            response = self.post_selected(photos)
        self.assertContains(response, "Nenhuma fotografia foi excluída. Falharam: 2.")
        self.assertEqual(GardenPhoto.objects.filter(pk__in=[item.pk for item in photos]).count(), 2)
