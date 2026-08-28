from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from crops.models import Crop, Cultivar
from crops.selectors import get_available_crops, get_public_crops
from subscriptions.models import Plan, PlanVersion


class CropCommercialFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        plan = Plan.objects.create(name="Essencial", code="essencial-crop-test", is_active=True, is_public=True)
        cls.version = PlanVersion.objects.create(plan=plan, version=1, price_cents=14990, effective_from=timezone.now())
        cls.lettuce = Crop.objects.create(common_name="Alface", code="alface-flow", category="Folhosa", is_available=True)
        cls.thyme = Crop.objects.create(common_name="Tomilho", code="tomilho-flow", category="Erva", is_available=True)
        cls.basil = Crop.objects.create(common_name="Manjericão", code="manjericao-flow", is_available=False)
        for name in ("Crespa", "Americana", "Mimosa"):
            Cultivar.objects.create(crop=cls.lettuce, name=name, is_active=True)

    def open_crop_step(self):
        session = self.client.session
        session["checkout"] = {"plan": str(self.version.pk)}
        session.save()
        return self.client.get(reverse("checkout", args=[2]))

    def test_available_crop_without_cultivar_appears_in_checkout(self):
        response = self.open_crop_step()
        self.assertContains(response, "Tomilho")
        self.assertContains(response, f'value="{self.thyme.pk}"', html=False)

    def test_inactive_crop_does_not_appear(self):
        self.assertNotContains(self.open_crop_step(), "Manjericão")

    def test_crop_with_three_cultivars_has_one_checkout_card(self):
        response = self.open_crop_step()
        self.assertContains(response, "Alface", count=1)
        for variety in ("Crespa", "Americana", "Mimosa"):
            self.assertNotContains(response, variety)

    def test_catalog_and_checkout_share_availability_rule(self):
        self.assertQuerySetEqual(get_available_crops(), get_public_crops(), transform=lambda crop: crop, ordered=True)
        catalog = self.client.get(reverse("crop-catalog"))
        checkout = self.open_crop_step()
        for name in ("Alface", "Tomilho"):
            self.assertContains(catalog, name)
            self.assertContains(checkout, name)

    def test_disabling_crop_removes_it_only_from_new_choices(self):
        self.thyme.is_available = False
        self.thyme.save(update_fields=["is_available"])
        self.assertFalse(get_available_crops().filter(pk=self.thyme.pk).exists())
        self.assertNotContains(self.open_crop_step(), "Tomilho")

    def test_planting_cycle_still_uses_cultivar(self):
        field = __import__("crops.models", fromlist=["PlantingCycle"]).PlantingCycle._meta.get_field("cultivar")
        self.assertEqual(field.remote_field.model, Cultivar)


class CropBackofficeUXTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="crop-admin@example.test", password="Strong-pass-2026!", full_name="Admin")
        self.client.force_login(self.admin)
        self.active = Crop.objects.create(common_name="Tomilho", code="tomilho-admin", category="Erva", is_available=True)
        self.inactive = Crop.objects.create(common_name="Sálvia", code="salvia-admin", category="Erva", is_available=False)

    def test_listing_uses_business_columns_and_status(self):
        response = self.client.get(reverse("ops-collection", args=["crops"]))
        for heading in ("Cultura", "Categoria", "Variedades", "Disponibilidade", "Cultivos"):
            self.assertContains(response, heading)
        self.assertContains(response, "ATIVA")
        self.assertContains(response, "INATIVA")
        self.assertNotContains(response, f'<td class="text-muted">{self.active.pk}</td>', html=False)

    def test_active_and_inactive_filters(self):
        active = self.client.get(reverse("ops-collection", args=["crops"]), {"status": "active"})
        self.assertContains(active, "Tomilho")
        self.assertNotContains(active, "Sálvia")
        inactive = self.client.get(reverse("ops-collection", args=["crops"]), {"status": "inactive"})
        self.assertNotContains(inactive, "Tomilho")
        self.assertContains(inactive, "Sálvia")

    def test_form_explains_availability(self):
        response = self.client.get(reverse("ops-create", args=["crops"]))
        self.assertContains(response, "Ativa e disponível")
        self.assertContains(response, "Manter inativa")
        self.assertContains(response, "poderá aparecer no catálogo e ser escolhida pelos clientes")
