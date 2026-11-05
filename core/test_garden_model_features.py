from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from gardens.models import GardenModel, GardenModelFeature
from subscriptions.models import Plan, PlanVersion


class GardenModelFeatureTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="features-admin@example.com", password="test1234", is_staff=True, is_superuser=True)
        self.model = GardenModel.objects.create(name="Modelo A", code="modelo-a", capacity=4)
        self.other = GardenModel.objects.create(name="Modelo B", code="modelo-b", capacity=8)
        self.feature = GardenModelFeature.objects.create(garden_model=self.model, name="Altura", value="85", unit="cm", icon="bi-arrows-vertical", display_order=1)

    def payload(self, total=1, **overrides):
        data = {
            "name": self.model.name, "code": self.model.code, "description": "",
            "capacity": 4, "photos_per_day": 4, "monitoring_interval_minutes": 60, "is_active": "on",
            "features-TOTAL_FORMS": str(total), "features-INITIAL_FORMS": "1",
            "features-MIN_NUM_FORMS": "0", "features-MAX_NUM_FORMS": "1000",
            "features-0-id": str(self.feature.pk), "features-0-garden_model": str(self.model.pk),
            "features-0-name": "Altura", "features-0-value": "90", "features-0-unit": "cm",
            "features-0-icon": "bi-arrows-vertical", "features-0-display_order": "0", "features-0-is_visible": "on",
        }
        data.update(overrides)
        return data

    def test_admin_adds_edits_reorders_hides_and_persists_features(self):
        self.client.force_login(self.admin)
        data = self.payload(2, **{
            "features-0-is_visible": "", "features-0-display_order": "2",
            "features-1-name": "Material", "features-1-value": "PLA/PETG", "features-1-unit": "",
            "features-1-icon": "bi-box", "features-1-display_order": "0", "features-1-is_visible": "on",
        })
        response = self.client.post(reverse("ops-edit", args=["garden-models", self.model.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.feature.refresh_from_db()
        self.assertEqual(self.feature.value, "90")
        self.assertFalse(self.feature.is_visible)
        self.assertTrue(self.model.physical_features.filter(name="Material", value="PLA/PETG", display_order=0).exists())
        reopened = self.client.get(reverse("ops-edit", args=["garden-models", self.model.pk]))
        self.assertContains(reopened, "PLA/PETG")

    def test_delete_is_scoped_to_the_model(self):
        foreign = GardenModelFeature.objects.create(garden_model=self.other, name="Peso", value="4,5", unit="kg")
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-edit", args=["garden-models", self.model.pk]), self.payload(**{"features-0-DELETE": "on"}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(GardenModelFeature.objects.filter(pk=self.feature.pk).exists())
        self.assertTrue(GardenModelFeature.objects.filter(pk=foreign.pk).exists())

    def test_public_page_only_shows_visible_non_empty_features(self):
        GardenModelFeature.objects.create(garden_model=self.model, name="ReservatÃ³rio", value="15", unit="L", display_order=0)
        GardenModelFeature.objects.create(garden_model=self.model, name="Oculta", value="segredo", is_visible=False)
        plan = Plan.objects.create(garden_model=self.model, name="Plano", code="plano-features", is_active=True, is_public=True)
        PlanVersion.objects.create(plan=plan, version=1, price_cents=10000, effective_from=timezone.now())
        response = self.client.get(reverse("plans"))
        self.assertContains(response, "ReservatÃ³rio")
        self.assertContains(response, "15 L")
        self.assertNotContains(response, "segredo")
        self.assertNotContains(response, "â€” mudas")

    def test_non_admin_cannot_open_operations_editor(self):
        user = User.objects.create_user(email="customer-features@example.com", password="test1234")
        self.client.force_login(user)
        self.assertNotEqual(self.client.get(reverse("ops-edit", args=["garden-models", self.model.pk])).status_code, 200)

    def test_technician_cannot_edit_physical_features(self):
        technician = User.objects.create_user(email="technician-features@example.com", password="test1234", employee_role=User.EmployeeRole.TECHNICIAN)
        self.client.force_login(technician)
        self.assertEqual(self.client.get(reverse("ops-edit", args=["garden-models", self.model.pk])).status_code, 403)
