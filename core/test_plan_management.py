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

    def test_legacy_plan_crud_routes_use_the_transactional_editor(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("ops-collection", args=["plans"])), reverse("ops-plan-management"))
        self.assertRedirects(self.client.get(reverse("ops-create", args=["plans"])), reverse("ops-plan-create"))
        self.assertRedirects(self.client.get(reverse("ops-edit", args=["plans", self.plan.pk])), reverse("ops-plan-edit", args=[self.plan.pk]))
        self.assertRedirects(self.client.get(reverse("ops-detail", args=["plans", self.plan.pk])), reverse("ops-plan-detail", args=[self.plan.pk]))

    def test_subscription_edit_persists_after_new_database_query(self):
        organization = Organization.objects.create(name="Assinante", slug="assinante-persistencia")
        subscription = Subscription.objects.create(
            organization=organization, plan_version=self.version, status=Subscription.Status.TRIALING,
            current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30),
            contracted_price_cents=10000, billing_day=5, notes="Antes",
        )
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-edit", args=["subscriptions", subscription.pk]), {
            "organization": str(organization.pk), "plan_version": str(self.version.pk), "status": Subscription.Status.ACTIVE,
            "current_period_start": subscription.current_period_start.strftime("%Y-%m-%dT%H:%M"),
            "current_period_end": subscription.current_period_end.strftime("%Y-%m-%dT%H:%M"),
            "contracted_price_cents": "12500", "billing_day": "12", "next_billing_at": "",
            "auto_renew": "on", "coupon": "", "discount_cents": "0", "canceled_at": "",
            "cancellation_reason": "", "notes": "Alteracao persistida", "provider": "manual", "provider_reference": "TEST-SUB-1",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        persisted = Subscription.objects.get(pk=subscription.pk)
        self.assertEqual(persisted.status, Subscription.Status.ACTIVE)
        self.assertEqual(persisted.contracted_price_cents, 12500)
        self.assertEqual(persisted.billing_day, 12)
        self.assertEqual(persisted.notes, "Alteracao persistida")

    def test_admin_create_and_edit_forms_render(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("ops-plan-create")).status_code, 200)
        response = self.client.get(reverse("ops-plan-edit", args=[self.plan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Adicionar benefício")
        self.assertNotContains(response, "Tipo de benefício")

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

    def test_create_plan_does_not_mutate_selected_model_features(self):
        model = GardenModel.objects.create(name="Modelo de criacao", code="modelo-criacao", capacity=4)
        self.client.force_login(self.admin)
        payload = self._plan_payload(garden_model=str(model.pk), **{
            "features-TOTAL_FORMS": "1", "features-INITIAL_FORMS": "0", "features-MIN_NUM_FORMS": "0", "features-MAX_NUM_FORMS": "1000",
            "features-0-name": "Material", "features-0-value": "PLA/PETG", "features-0-unit": "",
            "features-0-icon": "bi-box", "features-0-display_order": "0", "features-0-is_visible": "on",
        })
        response = self.client.post(reverse("ops-plan-create"), payload)
        self.assertEqual(response.status_code, 302)
        created_plan = Plan.objects.get(code="plano-visual")
        self.assertEqual(created_plan.garden_model_id, model.pk)
        self.assertFalse(GardenModelFeature.objects.filter(garden_model_id=model.pk, name="Material").exists())

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

    def test_plan_image_accepts_jpeg_png_and_webp_and_is_served_after_reload(self):
        formats = (("JPEG", "image/jpeg", "foto.jpg"), ("PNG", "image/png", "foto.png"), ("WEBP", "image/webp", "foto.webp"))
        for image_format, content_type, filename in formats:
            with self.subTest(image_format=image_format):
                output = BytesIO()
                Image.new("RGB", (48, 36), "green").save(output, image_format)
                upload = SimpleUploadedFile(filename, output.getvalue(), content_type=content_type)
                form = PlanAdminForm({**self._plan_payload(), "code": self.plan.code, "name": self.plan.name}, {"image": upload}, instance=self.plan)
                self.assertTrue(form.is_valid(), form.errors)
                saved = form.save(); form.save_image(saved)
                persisted = Plan.objects.get(pk=self.plan.pk)
                self.assertTrue(persisted.image_data)
                self.assertEqual(persisted.image_content_type, "image/webp")
                image_response = self.client.get(persisted.display_image_url)
                self.assertEqual(image_response.status_code, 200)
                self.assertEqual(image_response["Content-Type"], "image/webp")

    def test_plan_image_falls_back_to_persistent_garden_model_image(self):
        output = BytesIO(); Image.new("RGB", (40, 40), "green").save(output, "PNG")
        model_form = GardenModelForm(
            {"name": "Modelo com imagem", "code": "modelo-com-imagem", "capacity": 4, "photos_per_day": 4, "monitoring_interval_minutes": 60, "is_active": "on"},
            {"image": SimpleUploadedFile("modelo.png", output.getvalue(), content_type="image/png")},
        )
        self.assertTrue(model_form.is_valid(), model_form.errors)
        model = model_form.save()
        self.plan.garden_model = model; self.plan.image_data = None; self.plan.image_url = ""; self.plan.save()
        persisted = Plan.objects.select_related("garden_model").get(pk=self.plan.pk)
        self.assertEqual(persisted.display_image_url, model.display_image_url)
        self.assertContains(self.client.get(reverse("plan-detail", args=[self.plan.code])), model.display_image_url)

    def test_empty_benefit_row_does_not_block_plan_save(self):
        self.client.force_login(self.admin)
        payload = self._plan_payload(name="Plano com linha vazia", code=self.plan.code, **{
            "benefits-TOTAL_FORMS": "2",
            "benefits-1-benefit_type": "", "benefits-1-name": "", "benefits-1-icon": "", "benefits-1-description": "",
            "benefits-1-quantity": "", "benefits-1-unit": "", "benefits-1-display_order": "0", "benefits-1-is_included": "on",
        })
        response = self.client.post(reverse("ops-plan-edit", args=[self.plan.pk]), payload)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        self.assertEqual(Plan.objects.get(pk=self.plan.pk).name, "Plano com linha vazia")
        self.assertEqual(self.plan.versions.order_by("-version").first().entitlements.count(), 1)

    def test_partially_filled_benefit_requires_name_and_rolls_back(self):
        self.client.force_login(self.admin)
        version_count = self.plan.versions.count()
        payload = self._plan_payload(name="Nao deve persistir", code=self.plan.code, **{
            "benefits-TOTAL_FORMS": "2", "benefits-1-benefit_type": "camera-monitoring",
            "benefits-1-name": "", "benefits-1-description": "Sem nome", "benefits-1-display_order": "1", "benefits-1-is_included": "on",
        })
        response = self.client.post(reverse("ops-plan-edit", args=[self.plan.pk]), payload)
        self.assertEqual(response.status_code, 200)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.name, "Plano Base")
        self.assertEqual(self.plan.versions.count(), version_count)
        self.assertIn("name", response.context["formset"].forms[1].errors)

    def test_plan_pages_render_utf8_without_mojibake(self):
        self.plan.commercial_title = "Essencial para sua família"
        self.plan.description = "Cultivo, iluminação e câmera"
        self.plan.save()
        self.client.force_login(self.admin)
        for url in (reverse("ops-plan-edit", args=[self.plan.pk]), reverse("ops-plan-detail", args=[self.plan.pk]), reverse("plans"), reverse("plan-detail", args=[self.plan.code])):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            text = response.content.decode("utf-8")
            for marker in ("Ã§", "Ã£", "Ã¡", "Ã©", "Â·", "â€”", "ðŸ", "�"):
                self.assertNotIn(marker, text)

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
        detail = self.client.get(reverse("plan-detail", args=[self.plan.code]))
        for label in ("Irrigação automatizada", "Iluminação LED grow", "Monitoramento online", "Câmera Wi-Fi", "Suporte técnico", "Acesso à plataforma"):
            self.assertContains(detail, label)
        for label in ("Relatórios e históricos", "Programação de iluminação", "Programação de irrigação"):
            self.assertContains(detail, label)
        self.assertNotContains(detail, "Visita mensal")

    def test_admin_detail_uses_standard_catalog_and_hides_commercial_history(self):
        model = GardenModel.objects.create(
            name="Modelo specs", code="modelo-specs", capacity=7, reservoir_liters="18.50",
            height_cm="90", width_cm="45", depth_cm="35",
        )
        self.plan.garden_model = model
        self.plan.save(update_fields=["garden_model", "updated_at"])
        self.client.force_login(self.admin)
        response = self.client.get(reverse("ops-plan-detail", args=[self.plan.pk]))
        self.assertContains(response, "Características do plano")
        self.assertContains(response, "Serviços incluídos")
        self.assertContains(response, "7 plantas")
        self.assertContains(response, "18,50 L")
        self.assertContains(response, "90 × 45 × 35 cm")
        self.assertNotContains(response, "Histórico comercial")

    def test_public_model_specs_are_isolated_and_missing_values_are_omitted(self):
        model = GardenModel.objects.create(name="Modelo A specs", code="modelo-a-specs", capacity=4, reservoir_liters="8")
        other = GardenModel.objects.create(name="Modelo B specs", code="modelo-b-specs", capacity=12, reservoir_liters="25", height_cm="120", width_cm="50", depth_cm="40")
        self.plan.garden_model = model
        self.plan.save(update_fields=["garden_model", "updated_at"])
        other_plan = Plan.objects.create(name="Outro plano specs", code="outro-plano-specs", garden_model=other, is_active=True, is_public=True)
        PlanVersion.objects.create(plan=other_plan, version=1, price_cents=20000, effective_from=timezone.now())
        first = self.client.get(reverse("plan-detail", args=[self.plan.code]))
        second = self.client.get(reverse("plan-detail", args=[other_plan.code]))
        self.assertContains(first, "4 plantas")
        self.assertNotContains(first, "120 × 50 × 40")
        self.assertContains(second, "12 plantas")
        self.assertContains(second, "120 × 50 × 40 cm")

    def test_numeric_code_opens_the_correct_eligible_plan(self):
        self.plan.code = "02"; self.plan.save(update_fields=["code"])
        response = self.client.get(reverse("plan-detail", args=["02"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plano Base")
        self.assertEqual(self.client.get(reverse("plan-detail", args=["99"])).status_code, 404)

    def test_publication_diagnostics_allow_missing_model(self):
        self.version.retired_at = timezone.now() - timedelta(minutes=1); self.version.save()
        diagnostic = plan_publication_diagnostics(self.plan)
        self.assertNotIn("Preço não cadastrado", diagnostic["issues"])
        self.assertNotIn("modelo físico associado", " ".join(diagnostic["issues"]))
        self.assertTrue(diagnostic["is_published"])

    def test_garden_model_values_are_reflected_publicly(self):
        model = GardenModel.objects.create(name="Premium", code="premium-model", capacity=12, reservoir_liters=20, height_cm=260)
        GardenModelFeature.objects.create(garden_model=model, name="Mudas", value="12", unit="mudas", display_order=0)
        GardenModelFeature.objects.create(garden_model=model, name="Reservatorio", value="20", unit="L", display_order=1)
        GardenModelFeature.objects.create(garden_model=model, name="Altura", value="260", unit="cm", display_order=2)
        self.plan.garden_model = model; self.plan.save()
        response = self.client.get(reverse("plans"))
        self.assertContains(response, "12 plantas")
        self.assertContains(response, "20")
        self.assertNotContains(response, "260 cm")

    def test_plan_editor_does_not_mutate_shared_physical_features(self):
        model = GardenModel.objects.create(name="Modelo bÃ¡sico", code="modelo-basico", capacity=1)
        untouched_model = GardenModel.objects.create(name="Outro modelo", code="outro-modelo", capacity=9)
        untouched = GardenModelFeature.objects.create(garden_model=untouched_model, name="Peso", value="4,5", unit="kg")
        self.plan.garden_model = model
        self.plan.save(update_fields=["garden_model", "updated_at"])
        shared_plan = Plan.objects.create(name="Plano compartilhado", code="plano-compartilhado", garden_model=model)
        self.client.force_login(self.admin)
        payload = self._plan_payload(
            name=self.plan.name, code=self.plan.code, garden_model=str(model.pk), monthly_price="100.00",
            **{
                "features-TOTAL_FORMS": "3", "features-INITIAL_FORMS": "0", "features-MIN_NUM_FORMS": "0", "features-MAX_NUM_FORMS": "1000",
                "features-0-name": "Quantidade de mudas", "features-0-value": "4", "features-0-unit": "mudas", "features-0-icon": "bi-flower1", "features-0-display_order": "0", "features-0-is_visible": "on",
                "features-1-name": "ReservatÃ³rio", "features-1-value": "5", "features-1-unit": "L", "features-1-icon": "bi-droplet", "features-1-display_order": "1", "features-1-is_visible": "on",
                "features-2-name": "Altura", "features-2-value": "70", "features-2-unit": "cm", "features-2-icon": "bi-arrows-vertical", "features-2-display_order": "2", "features-2-is_visible": "on",
            },
        )
        response = self.client.post(reverse("ops-plan-edit", args=[self.plan.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(model.physical_features.exists())
        self.assertEqual(shared_plan.garden_model_id, model.pk)
        untouched.refresh_from_db()
        self.assertEqual(untouched.value, "4,5")
        return
        self.assertEqual(model.physical_features.get(name="Quantidade de mudas").value, "4")
        self.assertEqual(model.physical_features.get(name="ReservatÃ³rio").value, "5")
        height = model.physical_features.get(name="Altura")
        self.assertEqual(height.value, "70")
        reopened = self.client.get(reverse("ops-plan-edit", args=[self.plan.pk]))
        self.assertContains(reopened, "70")

        for index, feature in enumerate(model.physical_features.order_by("display_order")):
            payload[f"features-{index}-id"] = str(feature.pk)
            payload[f"features-{index}-garden_model"] = str(model.pk)
        payload["features-INITIAL_FORMS"] = "3"
        height_index = list(model.physical_features.order_by("display_order")).index(height)
        payload[f"features-{height_index}-value"] = "80"
        response = self.client.post(reverse("ops-plan-edit", args=[self.plan.pk]), payload)
        self.assertEqual(response.status_code, 302)
        height.refresh_from_db(); untouched.refresh_from_db()
        self.assertEqual(height.value, "80")
        self.assertEqual(shared_plan.garden_model.physical_features.get(name="Altura").value, "80")
        self.assertEqual(untouched.value, "4,5")
        self.assertContains(self.client.get(reverse("plans")), "80 cm")
        for url in (reverse("ops-plan-detail", args=[self.plan.pk]), reverse("plan-detail", args=[self.plan.code])):
            detail = self.client.get(url)
            self.assertContains(detail, "4 mudas")
            self.assertContains(detail, "80 cm")

        reservoir_index = next(index for index, feature in enumerate(model.physical_features.order_by("display_order")) if feature.name == "ReservatÃ³rio")
        payload[f"features-{reservoir_index}-DELETE"] = "on"
        response = self.client.post(reverse("ops-plan-edit", args=[self.plan.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(GardenModelFeature.objects.filter(garden_model=model, name="ReservatÃ³rio").exists())
        self.assertEqual(GardenModelFeature.objects.get(pk=height.pk).value, "80")
        for url in (reverse("ops-plan-edit", args=[self.plan.pk]), reverse("ops-plan-detail", args=[self.plan.pk]), reverse("plan-detail", args=[self.plan.code])):
            self.assertNotContains(self.client.get(url), "5 L")

    def test_plan_editor_ignores_physical_feature_payload(self):
        model = GardenModel.objects.create(name="Modelo validaÃ§Ã£o", code="modelo-validacao", capacity=4)
        feature = GardenModelFeature.objects.create(garden_model=model, name="Altura", value="60", unit="cm", icon="bi-arrows-vertical")
        self.plan.garden_model = model
        self.plan.description = "DescriÃ§Ã£o original"
        self.plan.save(update_fields=["garden_model", "description", "updated_at"])
        self.client.force_login(self.admin)
        payload = self._plan_payload(
            name=self.plan.name, code=self.plan.code, description="NÃ£o deve salvar", garden_model=str(model.pk), monthly_price="100.00",
            **{
                "features-TOTAL_FORMS": "1", "features-INITIAL_FORMS": "1", "features-MIN_NUM_FORMS": "0", "features-MAX_NUM_FORMS": "1000",
                "features-0-id": str(feature.pk), "features-0-garden_model": str(model.pk), "features-0-name": "Altura",
                "features-0-value": "", "features-0-unit": "cm", "features-0-icon": "bi-arrows-vertical", "features-0-display_order": "0", "features-0-is_visible": "on",
            },
        )
        response = self.client.post(reverse("ops-plan-edit", args=[self.plan.pk]), payload)
        self.assertEqual(response.status_code, 302)
        self.plan.refresh_from_db(); feature.refresh_from_db()
        self.assertNotEqual(self.plan.description, "Descrição original")
        self.assertEqual(feature.value, "60")
        return
        self.plan.refresh_from_db(); feature.refresh_from_db()
        self.assertEqual(self.plan.description, "DescriÃ§Ã£o original")
        self.assertEqual(feature.value, "60")
        self.assertIn("value", response.context["feature_formset"].forms[0].errors)

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

    def test_publish_without_model_or_complementary_content(self):
        self.plan.is_public = False; self.plan.description = ""; self.plan.short_copy = ""; self.plan.commercial_title = ""; self.plan.save()
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-plan-publish", args=[self.plan.pk]), {"action": "publish"}, follow=True)
        self.plan.refresh_from_db()
        self.assertTrue(self.plan.is_public)
        self.assertContains(response, "publicado com sucesso")

    def test_model_data_endpoint_updates_selected_model_without_saving_plan(self):
        model = GardenModel.objects.create(
            name="Modelo completo", code="modelo-endpoint", capacity=6,
            reservoir_liters="12.50", height_cm="82.00", width_cm="40.00", depth_cm="35.00",
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("ops-plan-model-data", args=[model.pk]))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["is_complete"])
        self.assertEqual(payload["missing"], [])
        self.assertEqual({item["key"] for item in payload["features"]}, {"capacity", "reservoir_liters", "height_cm", "width_cm", "depth_cm"})
        self.plan.refresh_from_db()
        self.assertIsNone(self.plan.garden_model_id)

    def test_model_data_endpoint_is_admin_only(self):
        model = GardenModel.objects.create(name="Restrito", code="modelo-restrito", capacity=4)
        user = User.objects.create_user(email="cliente-modelo@example.test", password="Strong-pass-2026!")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("ops-plan-model-data", args=[model.pk])).status_code, 403)

    def test_inactive_legacy_model_still_loads_in_plan_editor(self):
        model = GardenModel.objects.create(name="Modelo legado", code="modelo-legado-endpoint", capacity=4, is_active=False)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("ops-plan-model-data", args=[model.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Modelo legado")

    def test_plan_code_is_generated_when_omitted(self):
        form = PlanAdminForm(self._plan_payload(name="Plano Código Automático", code=""))
        self.assertTrue(form.is_valid(), form.errors)
        plan = form.save()
        self.assertEqual(plan.code, "plano-codigo-automatico")

    def test_delete_unused_plan_and_archive_used_plan(self):
        unused = Plan.objects.create(name="Descartável", code="descartavel")
        PlanVersion.objects.create(plan=unused, version=1, price_cents=5000, effective_from=timezone.now())
        self.client.force_login(self.admin)
        response = self.client.post(reverse("ops-plan-delete", args=[unused.pk]))
        self.assertRedirects(response, reverse("ops-plan-management"))
        self.assertFalse(Plan.objects.filter(pk=unused.pk).exists())

        organization = Organization.objects.create(name="Histórico", slug="historico-plano")
        subscription = Subscription.objects.create(
            organization=organization, plan_version=self.version, status=Subscription.Status.ACTIVE,
            current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30),
        )
        response = self.client.post(reverse("ops-plan-delete", args=[self.plan.pk]))
        self.assertRedirects(response, reverse("ops-plan-management"))
        self.plan.refresh_from_db(); subscription.refresh_from_db()
        self.assertFalse(self.plan.is_active)
        self.assertFalse(self.plan.is_public)
        self.assertEqual(subscription.plan_version_id, self.version.pk)

    def test_non_admin_cannot_delete_plan(self):
        user = User.objects.create_user(email="sem-permissao-plan@example.test", password="Strong-pass-2026!")
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse("ops-plan-delete", args=[self.plan.pk])).status_code, 403)
        self.assertTrue(Plan.objects.filter(pk=self.plan.pk).exists())

    def test_legacy_public_plan_without_dimensions_remains_publishable(self):
        model = GardenModel.objects.create(name="Legado", code="legado-incompleto", capacity=4)
        self.plan.garden_model = model
        self.plan.save(update_fields=["garden_model", "updated_at"])
        diagnostic = plan_publication_diagnostics(self.plan)
        self.assertEqual(diagnostic["publication_state"], "published")
        self.assertEqual(diagnostic["blocking_issues"], [])
        self.plan.refresh_from_db()
        self.assertTrue(self.plan.is_public)

    def test_model_measurements_persist_and_reject_zero(self):
        data = {
            "name": "Modelo técnico", "code": "modelo-tecnico", "capacity": "8",
            "reservoir_liters": "15.75", "height_cm": "90.50", "width_cm": "42.25",
            "depth_cm": "31.10", "photos_per_day": "4", "monitoring_interval_minutes": "60", "is_active": "on",
        }
        form = GardenModelForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        model = form.save()
        persisted = GardenModel.objects.get(pk=model.pk)
        self.assertEqual(str(persisted.reservoir_liters), "15.75")
        self.assertEqual(str(persisted.height_cm), "90.50")
        data["code"] = "modelo-invalido"
        data["reservoir_liters"] = "0"
        invalid = GardenModelForm(data)
        self.assertFalse(invalid.is_valid())
        self.assertIn("reservoir_liters", invalid.errors)

    def test_deactivation_keeps_versions(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("ops-plan-toggle", args=[self.plan.pk]))
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.is_active)
        self.assertTrue(PlanVersion.objects.filter(pk=self.version.pk).exists())
