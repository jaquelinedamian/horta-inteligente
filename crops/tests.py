from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from accounts.models import User
from core.backoffice_forms import CropForm
from .models import Crop, Cultivar
from .selectors import get_available_crops, get_available_cultivars


class SupportedCropCatalogTests(TestCase):
    def setUp(self):
        self.alface = Crop.objects.get(code="alface")
        self.tomilho = Crop.objects.get(code="tomilho")
        self.coentro = Crop.objects.get(code="coentro")
        self.legacy = Crop.objects.create(common_name="Manjericão", code="manjericao", is_available=True)

    def test_only_supported_crops_are_offered_in_required_order(self):
        self.assertEqual(list(get_available_crops().values_list("code", flat=True)), ["alface", "tomilho", "coentro"])

    def test_legacy_crop_cultivars_are_not_available_for_new_records(self):
        legacy = Cultivar.objects.create(crop=self.legacy, name="Genovês")
        supported = Cultivar.objects.create(crop=self.alface, name="Crespa")
        self.assertNotIn(legacy, get_available_cultivars())
        self.assertIn(supported, get_available_cultivars())

    def test_legacy_crop_detail_is_not_public(self):
        response = self.client.get(f"/culturas/{self.legacy.code}/")
        self.assertEqual(response.status_code, 404)


class CropImageTests(TestCase):
    def setUp(self):
        self.crop = Crop.objects.get(code="alface")

    def image_upload(self, image_format="PNG", size=(1600, 1200)):
        output = BytesIO()
        Image.new("RGB", size, "green").save(output, format=image_format)
        return SimpleUploadedFile("alface.png", output.getvalue(), content_type="image/png")

    def test_image_is_optimized_and_persisted_in_database(self):
        form = CropForm({
            "common_name": self.crop.common_name, "scientific_name": self.crop.scientific_name,
            "code": self.crop.code, "description": "Alface fresca", "is_available": "True",
            "light_hours": "13", "irrigation_frequency_period": "day",
        }, {"image": self.image_upload()}, instance=self.crop)
        self.assertTrue(form.is_valid(), form.errors)
        crop = form.save()
        self.assertEqual(crop.image_content_type, "image/webp")
        self.assertTrue(crop.image_data)
        with Image.open(BytesIO(bytes(crop.image_data))) as optimized:
            self.assertEqual(optimized.format, "WEBP")
            self.assertLessEqual(optimized.width, 1200)
        response = self.client.get(reverse("crop-image", args=[crop.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")

    def test_remove_image_keeps_crop_record(self):
        self.crop.image_data = b"image"
        self.crop.image_content_type = "image/webp"
        self.crop.save()
        form = CropForm({
            "common_name": self.crop.common_name, "scientific_name": self.crop.scientific_name,
            "code": self.crop.code, "is_available": "True", "remove_image": "on",
            "irrigation_frequency_period": "day",
        }, instance=self.crop)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.save().image_data)

    def test_technician_can_view_but_cannot_edit_botanical_data(self):
        technician = User.objects.create_user(
            email="tech-crops@example.test", password="safe-password",
            full_name="Técnico", employee_role=User.EmployeeRole.TECHNICIAN,
        )
        self.client.force_login(technician)
        self.assertEqual(self.client.get(reverse("ops-detail", args=["crops", self.crop.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("ops-edit", args=["crops", self.crop.pk])).status_code, 403)

    def test_availability_switch_loads_current_state_and_saves_only_on_submit(self):
        self.crop.is_available = True
        self.crop.save(update_fields=["is_available"])
        unbound = CropForm(instance=self.crop)
        self.assertTrue(unbound["is_available"].value())
        self.assertIn('role="switch"', str(unbound["is_available"]))

        bound = CropForm({
            "common_name": self.crop.common_name, "scientific_name": self.crop.scientific_name,
            "code": self.crop.code, "description": self.crop.description,
            "irrigation_frequency_period": self.crop.irrigation_frequency_period,
        }, instance=self.crop)
        self.assertTrue(bound.is_valid(), bound.errors)
        self.assertTrue(Crop.objects.get(pk=self.crop.pk).is_available)
        bound.save()
        self.crop.refresh_from_db()
        self.assertFalse(self.crop.is_available)

# Create your tests here.
