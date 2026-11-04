from django.test import TestCase

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

# Create your tests here.
