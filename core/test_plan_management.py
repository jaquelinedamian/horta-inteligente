from datetime import timedelta
from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core.backoffice_forms import CommercialPlanForm, GardenModelForm
from core.plan_forms import PlanAdminForm
from subscriptions.models import Plan, PlanEntitlement, PlanVersion, Subscription
from accounts.models import Organization
from gardens.models import GardenModel, GardenModelFeature
from subscriptions.selectors import get_plan_price_state, plan_publication_diagnostics
from subscriptions.selectors import get_current_plan_version


class PlanManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="plan-admin@example.test", password="Strong-pass-2026!", full_name="Admin")
        self.plan = Plan.objects.create(name="Plano Base", code="plano-base", is_active=True, is_public=True)
        self.version = PlanVersion.objects.create(plan=self.plan, version=1, price_cents=10000, effective_from=timezone.now() - timedelta(days=1))

    def test_removed_textarea_items_are_really_deleted(self):
        PlanEntitlement.objects.create(plan_version=self.version, benefit_type="item-1", name="Mantido")
        PlanEntitlement.objects.create(plan_version=self.version, benefit_type="item-2", name="Removido")
        form = CommercialPlanForm({"name": self.plan.name, "code": self.plan.code, "monthly_price": "100.00", "included_items": "Mantido", "is_active": "on", "is_public": "on"}, instance=self.plan)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(list(self.version.entitlements.values_list("name", flat=True)), ["Mantido"])

    def test_catalog_uses_latest_version_without_date_dependency(self):
        future = timezone.now() + timedelta(days=10)
        self.version.retired_at = future
        self.version.save()
        PlanVersion.objects.create(plan=self.plan, version=2, price_cents=12000, effective_from=future)
        self.assertEqual(get_current_plan_version(self.plan).version, 2)

    def test_management_is_admin_only(self):
        user = User.objects.create_user(email="customer-plan@example.test", password="Strong-pass-2026!")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("ops-plan-management")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("ops-plan-management")).status_code, 200)

    def test_admin_create_and_edit_forms_render(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("ops-plan-create")).status_code, 200)
        response = self.client.get(reverse("ops-plan-edit", args=[self.plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Serviços incluídos")

    def _plan_payload(self, **changes):
        data = {
            "name": "Plano Visual", "commercial_title": "Horta em casa", "short_copy": "Plano integrado",
            "description": "Descrição", "code": "plano-visual", "display_order": "1",
            "monthly_price": "149.90", "installation_fee": "250.00", "is_active": "on", "is_public": "on",
            "benefits-TOTAL_FORMS": "1", "benefits-INITIAL_FORMS": "0", "benefits-MIN_NUM_FORMS": "0", "benefits-MAX_NUM_FORMS": "1000",
            "benefits-0-name": "Suporte técnico", "benefits-0-icon": "bi-headset", "benefits-0-description": "Atendimento",
            "benefits-0-quantity": "1", "benefits-0-unit": "visitas/mês", "benefits-0-display_order": "0", "benefits-0-is_included": "on",
        }
        data.update(changes)
        return data

    def test_create_plan_persists_currency_and_benefit(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-plan-create"), self._plan_payload())
        self.assertEqual(response.status_code, 302)
        plan = Plan.objects.get(code="plano-visual")
        self.assertEqual(plan.installation_fee_cents, 25000)
        self.assertEqual(plan.versions.get().price_cents, 14990)
        self.assertEqual(plan.versions.get().entitlements.get().name, "Suporte técnico")

    def test_image_upload_replace_and_remove(self):
        def uploaded(color):
            output = BytesIO(); Image.new("RGB", (32, 32), color).save(output, "PNG")
            return SimpleUploadedFile("horta.png", output.getvalue(), content_type="image/png")
        form = PlanAdminForm({**self._plan_payload(), "benefits-TOTAL_FORMS": "0"}, {"image": uploaded("green")}, instance=self.plan)
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(); form.save_image(plan); first = bytes(plan.image_data)
        form = PlanAdminForm({**self._plan_payload(), "code": self.plan.code, "name": self.plan.name, "remove_image": ""}, {"image": uploaded("blue")}, instance=plan)
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(); form.save_image(plan)
        self.assertNotEqual(first, bytes(plan.image_data))
        form = PlanAdminForm({**self._plan_payload(), "code": self.plan.code, "name": self.plan.name, "remove_image": "on"}, instance=plan)
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(); form.save_image(plan)
        self.assertIsNone(plan.image_data)

    def test_garden_model_image_is_persistent_and_served(self):
        output = BytesIO(); Image.new("RGB", (32, 32), "green").save(output, "PNG")
        image = SimpleUploadedFile("modelo.png", output.getvalue(), content_type="image/png")
        form = GardenModelForm({"name": "Modelo foto", "code": "modelo-foto", "capacity": 3, "photos_per_day": 4, "monitoring_interval_minutes": 60, "is_active": "on"}, {"image": image})
        self.assertTrue(form.is_valid(), form.errors)
        model = form.save(); model.refresh_from_db()
        self.assertTrue(model.image_data)
        self.assertEqual(self.client.get(model.display_image_url).status_code, 200)

    def test_new_price_version_preserves_existing_contract(self):
        organization = Organization.objects.create(name="Cliente", slug="cliente-plan-version")
        subscription = Subscription.objects.create(organization=organization, plan_version=self.version, contracted_price_cents=10000, status=Subscription.Status.ACTIVE, current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30))
        form = PlanAdminForm({**self._plan_payload(), "code": self.plan.code, "name": self.plan.name, "monthly_price": "199.90"}, instance=self.plan)
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save(); new_version = form.create_version(plan, self.version)
        subscription.refresh_from_db()
        self.assertEqual(subscription.plan_version_id, self.version.pk)
        self.assertEqual(subscription.contracted_price_cents, 10000)
        self.assertEqual(new_version.price_cents, 19990)

    def test_comparison_and_navigation_are_dynamic(self):
        PlanEntitlement.objects.create(plan_version=self.version, benefit_type="camera", name="Câmera", is_included=True)
        response = self.client.get(reverse("plans"))
        self.assertContains(response, "Câmera")
        self.assertContains(response, 'aria-current="page"')
        for name in ("home", "how-it-works", "crop-catalog", "about", "faq"):
            self.assertContains(self.client.get(reverse(name)), 'aria-current="page"')

    def test_public_card_selects_the_exact_version(self):
        response = self.client.get(reverse("checkout-plan", args=[self.version.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["checkout"]["plan"], str(self.version.pk))

    def test_public_plan_and_detail_use_the_same_data(self):
        PlanEntitlement.objects.create(plan_version=self.version, benefit_type="item-1", name="Visita mensal", is_included=True)
        for url in (reverse("plans"), reverse("plan-detail", args=[self.plan.code])):
            response = self.client.get(url)
            self.assertContains(response, "Plano Base")
            self.assertContains(response, "Visita mensal")

    def test_numeric_code_opens_the_correct_eligible_plan(self):
        self.plan.code = "02"; self.plan.save(update_fields=["code"])
        response = self.client.get(reverse("plan-detail", args=["02"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plano Base")
        self.assertEqual(self.client.get(reverse("plan-detail", args=["99"])).status_code, 404)

    def test_publication_diagnostics_explain_missing_version_and_model(self):
        self.version.retired_at = timezone.now() - timedelta(minutes=1); self.version.save()
        diagnostic = plan_publication_diagnostics(self.plan)
        self.assertNotIn("Preço não cadastrado", diagnostic["issues"])
        self.assertIn("Associe um modelo de horta", diagnostic["issues"])
        self.assertTrue(diagnostic["is_published"])

    def test_garden_model_values_are_reflected_publicly(self):
        model = GardenModel.objects.create(name="Premium", code="premium-model", capacity=12, reservoir_liters=20, height_cm=260)
        self.plan.garden_model = model; self.plan.save()
        response = self.client.get(reverse("plans"))
        self.assertContains(response, "12 mudas")
        self.assertContains(response, "20")
        self.assertContains(response, "260")

    def test_plan_editor_persists_and_updates_physical_features(self):
        model = GardenModel.objects.create(name="Modelo bÃ¡sico", code="modelo-basico", capacity=1)
        untouched_model = GardenModel.objects.create(name="Outro modelo", code="outro-modelo", capacity=9)
        untouched = GardenModelFeature.objects.create(garden_model=untouched_model, name="Peso", value="4,5", unit="kg")
        self.plan.garden_model = model
        self.plan.save(update_fields=["garden_model", "updated_at"])
        self.client.force_login(self.admin)
        payload = self._plan_payload(
            name=self.plan.name, code=self.plan.code, garden_model=str(model.pk), monthly_price="100.00",
            **{
                "features-TOTAL_FORMS": "3", "features-INITIAL_FORMS": "0", "features-MIN_NUM_FORMS": "0", "features-MAX_NUM_FORMS": "1000",
                "features-0-name": "Quantidade de mudas", "features-0-value": "4", "features-0-unit": "mudas", "features-0-icon": "bi-flower1", "features-0-display_order": "0", "features-0-is_visible": "on",
                "features-1-name": "ReservatÃ³rio", "features-1-value": "5", "features-1-unit": "L", "features-1-icon": "bi-droplet", "features-1-display_order": "1", "features-1-is_visible": "on",
                "features-2-name": "Altura", "features-2-value": "60", "features-2-unit": "cm", "features-2-icon": "bi-arrows-vertical", "features-2-display_order": "2", "features-2-is_visible": "on",
            },
        )
        response = self.client.post(reverse("ops-plan-edit", args=[self.plan.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(model.physical_features.get(name="Quantidade de mudas").value, "4")
        self.assertEqual(model.physical_features.get(name="ReservatÃ³rio").value, "5")
        height = model.physical_features.get(name="Altura")
        self.assertEqual(height.value, "60")
        reopened = self.client.get(reverse("ops-plan-edit", args=[self.plan.pk]))
        self.assertContains(reopened, "60")

        for index, feature in enumerate(model.physical_features.order_by("display_order")):
            payload[f"features-{index}-id"] = str(feature.pk)
            payload[f"features-{index}-garden_model"] = str(model.pk)
        payload["features-INITIAL_FORMS"] = "3"
        height_index = list(model.physical_features.order_by("display_order")).index(height)
        payload[f"features-{height_index}-value"] = "70"
        response = self.client.post(reverse("ops-plan-edit", args=[self.plan.pk]), payload)
        self.assertEqual(response.status_code, 302)
        height.refresh_from_db(); untouched.refresh_from_db()
        self.assertEqual(height.value, "70")
        self.assertEqual(untouched.value, "4,5")
        self.assertContains(self.client.get(reverse("plans")), "70 cm")

    def test_only_one_plan_remains_featured(self):
        self.plan.is_featured = True; self.plan.save()
        other = Plan.objects.create(name="Outro", code="outro", is_active=True, is_public=True)
        PlanVersion.objects.create(plan=other, version=1, price_cents=20000, effective_from=timezone.now())
        form = PlanAdminForm({**self._plan_payload(), "name": other.name, "code": other.code, "is_featured": "on"}, instance=other)
        self.assertTrue(form.is_valid(), form.errors)
        form.save(); self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_featured)
        self.assertTrue(other.is_featured)

    def test_quick_price_ignores_legacy_date_fields_and_is_immediate(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-plan-price-update", args=[self.plan.pk]), {
            "monthly_price": "180.00", "installation_fee": "90.00", "effective_from": "2099-01-01T10:00",
        })
        self.assertEqual(response.status_code, 302)
        state = get_plan_price_state(self.plan)
        self.assertEqual(state["status"], "current")
        self.assertEqual(state["current"].price_cents, 18000)
        self.assertIsNone(state["scheduled"])
        self.version.refresh_from_db()
        self.assertIsNotNone(self.version.retired_at)

    def test_forms_do_not_expose_or_require_effective_dates(self):
        form = PlanAdminForm(self._plan_payload(), instance=self.plan)
        self.assertNotIn("effective_from", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        legacy = CommercialPlanForm({"name": self.plan.name, "code": self.plan.code, "monthly_price": "100.00", "is_active": "on", "is_public": "on"}, instance=self.plan)
        self.assertNotIn("effective_from", legacy.fields)
        self.assertTrue(legacy.is_valid(), legacy.errors)

    def test_quick_price_update_creates_no_duplicate_for_same_value(self):
        self.client.force_login(self.admin)
        payload = {"monthly_price": "150.00", "installation_fee": "100.00", "apply_immediately": "on"}
        self.client.post(reverse("ops-plan-price-update", args=[self.plan.pk]), payload)
        count = self.plan.versions.count()
        self.client.post(reverse("ops-plan-price-update", args=[self.plan.pk]), payload)
        self.assertEqual(self.plan.versions.count(), count)
        self.assertEqual(get_plan_price_state(self.plan)["current"].price_cents, 15000)

    def test_publish_valid_plan_and_unpublish_without_touching_subscription(self):
        model = GardenModel.objects.create(name="Modelo válido", code="modelo-valido", capacity=3, reservoir_liters=5, height_cm=65)
        self.plan.garden_model = model; self.plan.description = "Plano comercial"; self.plan.is_public = False; self.plan.save()
        organization = Organization.objects.create(name="Contrato", slug="contrato-publicacao")
        subscription = Subscription.objects.create(organization=organization, plan_version=self.version, contracted_price_cents=10000, status=Subscription.Status.ACTIVE, current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30))
        self.client.force_login(self.admin)
        self.client.post(reverse("ops-plan-publish", args=[self.plan.pk]), {"action": "publish"})
        self.plan.refresh_from_db(); self.assertTrue(self.plan.is_public); self.assertContains(self.client.get(reverse("plans")), self.plan.name)
        self.client.post(reverse("ops-plan-publish", args=[self.plan.pk]), {"action": "unpublish"})
        self.plan.refresh_from_db(); subscription.refresh_from_db()
        self.assertFalse(self.plan.is_public)
        self.assertEqual(subscription.plan_version_id, self.version.pk)
        response = self.client.get(reverse("plans"))
        self.assertEqual(list(response.context["plans"]), [])

    def test_publish_is_blocked_with_clear_pending_requirements(self):
        self.plan.is_public = False; self.plan.description = ""; self.plan.short_copy = ""; self.plan.commercial_title = ""; self.plan.save()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-plan-publish", args=[self.plan.pk]), {"action": "publish"}, follow=True)
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_public)
        self.assertContains(response, "Associe um modelo de horta")

    def test_deactivation_keeps_versions(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("ops-plan-toggle", args=[self.plan.pk]))
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_active)
        self.assertTrue(PlanVersion.objects.filter(pk=self.version.pk).exists())
