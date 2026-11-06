import os
import base64
import logging
from datetime import timedelta
from io import BytesIO
from uuid import UUID

from django.conf import settings
from django import forms
from collections.abc import Mapping
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib import messages
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from accounts.models import Membership, Organization, User
from crops.models import Crop, CropLightingSchedule, Cultivar, PlantingCycle
from devices.models import Alert, Device, DeviceCredential, GardenPhoto
from gardens.models import Garden, GardenModel, GardenModule, ModuleInstallation
from gardens.selectors import get_active_installations
from gardens.configuration import effective_garden_configuration
from devices.selectors import garden_snapshot
from operations.models import InventoryItem, SupportTicket, Visit, WorkOrder
from subscriptions.models import CheckoutRequest, Payment, Plan, PlanEntitlement, Subscription
from subscriptions.selectors import plan_publication_diagnostics

from .backoffice import get_resource
from .backoffice_forms import ClientOnboardingForm, CustomerModuleForm, CustomerModuleInstallationForm, GardenModelFeatureFormSet, resource_form_class
from gardens.services import install_module
from .guided_flows import PRIMARY_ACTIONS, get_flow
from .workflow_services import create_customer, run_guided_workflow
from .permissions import admin_required, operations_required
from .plan_forms import PlanAdminForm, PlanEntitlementFormSet, PlanPriceForm, save_plan_price
from .automation import automation_panel_context
from .deletion_services import (
    DELETE_POLICIES, DeletionBlocked, can_deactivate, customer_deletion_summary,
    deactivate_object, delete_administrative_object, delete_customer_completely,
    object_deletion_summary, requires_strong_confirmation,
)

logger = logging.getLogger(__name__)


def _save_garden_model_features(formset, garden_model, *, source):
    submitted = formset.total_form_count()
    created = updated = removed = valid = 0
    for feature_form in formset.forms:
        if not feature_form.cleaned_data:
            continue
        deleting = feature_form.cleaned_data.get("DELETE", False)
        existed = not feature_form.instance._state.adding
        if deleting and existed:
            removed += 1
        elif not deleting and feature_form.cleaned_data.get("name"):
            valid += 1
            if existed and feature_form.has_changed():
                updated += 1
            elif not existed:
                created += 1
    formset.save()
    persisted = garden_model.physical_features.count()
    transaction.on_commit(lambda: logger.info(
        "garden_model_features_saved source=%s model_id=%s submitted=%s valid=%s created=%s updated=%s removed=%s persisted=%s transaction=committed",
        source, garden_model.pk, submitted, valid, created, updated, removed, persisted,
    ))
    return persisted


def _log_invalid_garden_model_features(formset, garden_model, *, source):
    error_forms = sum(bool(form.errors) for form in formset.forms)
    logger.warning(
        "garden_model_features_invalid source=%s model_id=%s submitted=%s error_forms=%s non_form_errors=%s transaction=not_started",
        source, getattr(garden_model, "pk", None), formset.total_form_count(), error_forms, len(formset.non_form_errors()),
    )


def _garden_model_preview_data():
    return list(GardenModel.objects.filter(is_active=True).values("id", "capacity", "reservoir_liters", "height_cm", "module_count"))


def _serialize_garden_model(model):
    return {
        "id": str(model.pk), "name": model.name, "description": model.description,
        "edit_url": reverse("ops-edit", args=["garden-models", model.pk]),
        "is_complete": bool(model.capacity and model.reservoir_liters and model.height_cm),
        "missing": [label for value, label in (
            (model.capacity, "quantidade máxima de plantas"),
            (model.reservoir_liters, "capacidade do reservatório"),
            (model.height_cm, "altura"),
        ) if not value],
        "features": [{**feature, "value": str(feature["value"])} for feature in model.technical_summary],
    }


@admin_required
def plan_model_data(request, model_id):
    model = get_object_or_404(GardenModel.objects.prefetch_related("physical_features"), pk=model_id, is_active=True)
    return JsonResponse(_serialize_garden_model(model))


def _copy_entitlements(formset, version):
    position = 0
    for item_form in formset.forms:
        if not item_form.cleaned_data or item_form.cleaned_data.get("DELETE") or not item_form.cleaned_data.get("name"):
            continue
        data = {key: item_form.cleaned_data.get(key) for key in ("benefit_type", "name", "icon", "description", "quantity", "unit", "display_order", "is_included", "is_featured")}
        data["display_order"] = data["display_order"] if data["display_order"] is not None else position
        if not data["benefit_type"]:
            searchable = f'{data.get("name", "")} {data.get("unit", "")}'.lower()
            type_hints = (
                ("visit", "maintenance-visits"), ("irriga", "automatic-irrigation"),
                ("ilumina", "programmable-lighting"), ("câmera", "camera-monitoring"),
                ("camera", "camera-monitoring"), ("sensor", "sensor-monitoring"),
                ("plataforma", "platform-access"), ("suporte", "technical-support"),
            )
            data["benefit_type"] = next((kind for hint, kind in type_hints if hint in searchable), f"item-{position + 1}")
        PlanEntitlement.objects.create(plan_version=version, **data)
        position += 1


@admin_required
def plan_management(request):
    plans = Plan.objects.select_related("garden_model").prefetch_related("versions__entitlements").order_by("display_order", "name")
    rows = []
    for plan in plans:
        diagnostic = plan_publication_diagnostics(plan)
        plan.publication_issues = diagnostic["issues"]
        plan.is_published = diagnostic["is_published"]
        plan.publication_state = diagnostic["publication_state"]
        plan.price_state = diagnostic["price"]
        plan.displayed_version = diagnostic["price"]["displayed"]
        plan.monthly_visits = None
        if diagnostic["price"]["displayed"]:
            plan.monthly_visits = diagnostic["price"]["displayed"].entitlements.filter(benefit_type="maintenance-visits", is_included=True).first()
        rows.append((plan, diagnostic["price"]["displayed"]))
    subscriptions = Subscription.objects.select_related("organization", "plan_version__plan").order_by("-created_at")[:100]
    return render(request, "admin_portal/plan_management.html", {"plan_rows": rows, "subscriptions": subscriptions})


@admin_required
@transaction.atomic
def plan_create(request):
    form = PlanAdminForm(request.POST or None, request.FILES or None)
    formset = PlanEntitlementFormSet(request.POST or None, prefix="benefits")
    form_valid = form.is_valid() if request.method == "POST" else False
    if request.method == "POST" and form_valid and formset.is_valid():
        plan = form.save(commit=False)
        plan.is_active, plan.is_public = True, False
        plan.save()
        form.save_image(plan)
        version = form.create_version(plan)
        _copy_entitlements(formset, version)
        messages.success(request, "Plano criado como rascunho. Revise os dados antes de publicar.")
        return redirect("ops-plan-detail", plan_id=plan.pk)
    return render(request, "admin_portal/plan_form.html", {"form": form, "formset": formset, "title": "Novo plano"})


@admin_required
@transaction.atomic
def plan_edit(request, plan_id):
    plan = get_object_or_404(Plan, pk=plan_id)
    current = plan.versions.order_by("-version", "-created_at").first()
    form = PlanAdminForm(request.POST or None, request.FILES or None, instance=plan)
    formset = PlanEntitlementFormSet(request.POST or None, instance=current, prefix="benefits") if current else PlanEntitlementFormSet(request.POST or None, prefix="benefits")
    form_valid = form.is_valid() if request.method == "POST" else False
    if request.method == "POST" and form_valid and formset.is_valid():
        plan = form.save()
        form.save_image(plan)
        version = form.create_version(plan, current)
        _copy_entitlements(formset, version)
        messages.success(request, f"Alterações salvas na versão {version.version}; contratos anteriores foram preservados.")
        return redirect("ops-plan-detail", plan_id=plan.pk)
    return render(request, "admin_portal/plan_form.html", {"form": form, "formset": formset, "title": f"Editar {plan.name}", "plan": plan})


@admin_required
def plan_detail_admin(request, plan_id):
    plan = get_object_or_404(Plan.objects.select_related("garden_model").prefetch_related("garden_model__physical_features"), pk=plan_id)
    versions = plan.versions.prefetch_related("entitlements").order_by("-version")
    diagnostic = plan_publication_diagnostics(plan)
    return render(request, "admin_portal/plan_detail.html", {"plan": plan, "versions": versions, "current": diagnostic["price"]["current"], "scheduled": diagnostic["price"]["scheduled"]})


@admin_required
@require_POST
def plan_toggle(request, plan_id):
    plan = get_object_or_404(Plan, pk=plan_id)
    plan.is_active = not plan.is_active
    plan.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Plano ativado." if plan.is_active else "Plano desativado para novas contratações; assinaturas existentes foram mantidas.")
    return redirect("ops-plan-management")


def _publication_requirements(plan):
    return plan_publication_diagnostics(plan)["blocking_issues"]


@admin_required
@require_POST
def plan_publish(request, plan_id):
    plan = get_object_or_404(Plan.objects.select_related("garden_model"), pk=plan_id)
    action = request.POST.get("action", "publish")
    if action == "unpublish":
        plan.is_public = False
        plan.save(update_fields=["is_public", "updated_at"])
        messages.success(request, f"{plan.name} deixou de ser oferecido para novas contratações.")
        return redirect("ops-plan-management")
    problems = _publication_requirements(plan)
    if problems:
        messages.error(request, f"Não foi possível publicar {plan.name}. Complete: " + ", ".join(problems) + ".")
        return redirect("ops-plan-management")
    plan.is_active = True
    plan.is_public = True
    plan.save(update_fields=["is_active", "is_public", "updated_at"])
    messages.success(request, f"{plan.name} foi publicado com sucesso.")
    return redirect("ops-plan-management")


@admin_required
@require_POST
def plan_price_update(request, plan_id):
    plan = get_object_or_404(Plan, pk=plan_id)
    form = PlanPriceForm(request.POST)
    if not form.is_valid():
        errors = " ".join(message for values in form.errors.values() for message in values)
        messages.error(request, f"Não foi possível alterar o preço de {plan.name}: {errors}")
        return redirect("ops-plan-management")
    version, created = save_plan_price(plan, form.cleaned_data)
    messages.success(request, f"Preço de {plan.name} salvo na versão {version.version}." if created else f"Preço de {plan.name} já estava configurado ou foi atualizado sem duplicação.")
    return redirect("ops-plan-management")


@admin_required
@require_POST
@transaction.atomic
def plan_duplicate(request, plan_id):
    source = get_object_or_404(Plan, pk=plan_id)
    current = source.versions.order_by("-version", "-created_at").first()
    source.pk = None
    source.name = f"{source.name} (cópia)"
    source.code = f"{source.code}-copia-{timezone.now():%H%M%S}"
    source.is_public = False
    source.is_active = False
    source.is_featured = False
    source.save()
    if current:
        duplicate = source.versions.create(version=1, price_cents=current.price_cents, effective_from=timezone.now(), installation_fee_cents=current.installation_fee_cents, commercial_snapshot=current.commercial_snapshot)
        for benefit in current.entitlements.all():
            benefit.pk = None
            benefit.plan_version = duplicate
            benefit.save()
    messages.success(request, "Plano duplicado como rascunho inativo.")
    return redirect("ops-plan-edit", plan_id=source.pk)


AREAS = {
    "comercial": ("Clientes", "Clientes da HortaViva.", ("clients",)),
    "configuracoes": ("Planos e assinaturas", "Configurações comerciais dos modelos de horta.", ("plans", "subscriptions")),
    "cultivo": ("Cultivo", "Catálogo agronômico, ciclos, colheitas e insumos.", ("crops", "crop-lighting", "cultivars", "cultivation-profiles", "crop-stages", "cycles", "harvests", "substrates", "substrate-recipes", "fertilizers", "nutrition-plans")),
    "hortas": ("Hortas", "Estrutura instalada, módulos e instalações.", ("gardens", "module-types", "modules", "installations", "qrcodes")),
    "iot": ("IoT", "Dispositivos, métricas, telemetria e automações.", ("device-models", "devices", "metrics", "channels", "telemetry", "calibrations", "commands", "alert-rules", "alerts", "lighting")),
    "operacao": ("Operação", "Agenda, ordens, manutenção e atendimento.", ("visits", "orders", "maintenance", "maintenance-records", "tickets")),
    "estoque": ("Estoque", "Itens, categorias, fornecedores, lotes e movimentações.", ("inventory", "inventory-categories", "suppliers", "stock-lots", "stock-movements")),
    "administracao": ("Administração", "Equipe e configurações operacionais.", ("employees", "settings")),
}


class GardenAdministrationForm(forms.ModelForm):
    class Meta:
        model = Garden
        fields = ("name", "garden_model", "address", "status", "primary_technician", "installed_at", "operational_notes")
        labels = {"operational_notes": "Observações", "primary_technician": "Técnico responsável", "installed_at": "Data de instalação"}
        widgets = {"installed_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "operational_notes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
        if organization:
            self.fields["address"].queryset = organization.addresses.order_by("label", "street")
        self.fields["primary_technician"].queryset = User.objects.filter(employee_role=User.EmployeeRole.TECHNICIAN, is_active=True).order_by("full_name")


CAMERA_COLOR_DEFAULTS = {
    "mode": "original", "temperature": 0, "hue": 0, "saturation": 100,
    "contrast": 100, "brightness": 100, "green_intensity": 100,
    "magenta_compensation": 0, "white_balance": True,
}


class CameraColorCalibrationForm(forms.Form):
    mode = forms.ChoiceField(choices=(
        ("original", "Original"), ("automatic", "Correção automática"),
        ("manual", "Calibração manual"),
    ))
    temperature = forms.IntegerField(min_value=-100, max_value=100)
    hue = forms.IntegerField(min_value=-180, max_value=180)
    saturation = forms.IntegerField(min_value=0, max_value=200)
    contrast = forms.IntegerField(min_value=50, max_value=150)
    brightness = forms.IntegerField(min_value=50, max_value=150)
    green_intensity = forms.IntegerField(min_value=50, max_value=150)
    magenta_compensation = forms.IntegerField(min_value=-100, max_value=100)
    white_balance = forms.BooleanField(required=False)


@admin_required
def camera_color_calibration(request, device_id):
    camera = get_object_or_404(
        Device.objects.select_related("garden", "organization"),
        pk=device_id, kind=Device.Kind.CAMERA,
    )
    metadata = camera.metadata if isinstance(camera.metadata, dict) else {}
    saved = metadata.get("color_calibration", {})
    profile = {**CAMERA_COLOR_DEFAULTS, **(saved if isinstance(saved, dict) else {})}
    form = CameraColorCalibrationForm(request.POST or None, initial=profile)
    if request.method == "POST":
        if request.POST.get("action") == "reset":
            updated_metadata = {**metadata, "color_calibration": CAMERA_COLOR_DEFAULTS.copy()}
            camera.metadata = updated_metadata
            camera.save(update_fields=["metadata", "updated_at"])
            messages.success(request, "Calibração restaurada para o padrão original.")
            return redirect("ops-camera-color-calibration", device_id=camera.pk)
        if form.is_valid():
            updated_metadata = {**metadata, "color_calibration": form.cleaned_data}
            camera.metadata = updated_metadata
            camera.save(update_fields=["metadata", "updated_at"])
            messages.success(request, "Perfil de calibração salvo para esta câmera.")
            return redirect("ops-camera-color-calibration", device_id=camera.pk)

    latest_photo = camera.photos.order_by("-captured_at", "-created_at").first()
    stream_url = None
    if camera.local_ip:
        host = f"[{camera.local_ip}]" if ":" in camera.local_ip else camera.local_ip
        stream_url = f"http://{host}/stream"
    return render(request, "admin_portal/camera_color_calibration.html", {
        "camera": camera, "form": form, "profile": profile,
        "latest_photo": latest_photo, "stream_url": stream_url,
        "defaults": CAMERA_COLOR_DEFAULTS,
    })


def _filtered_admin_photos(params):
    photos = GardenPhoto.objects.select_related("garden", "garden__organization", "device")
    garden_id = params.get("garden", "").strip()
    camera_id = params.get("camera", "").strip()
    period = params.get("period", "30d").strip()
    date_from = parse_date(params.get("date_from", ""))
    date_to = parse_date(params.get("date_to", ""))
    try:
        garden_uuid = UUID(garden_id) if garden_id else None
        camera_uuid = UUID(camera_id) if camera_id else None
    except (TypeError, ValueError):
        return photos.none()
    if garden_uuid:
        photos = photos.filter(garden_id=garden_id)
    if camera_uuid:
        photos = photos.filter(device_id=camera_id, device__kind=Device.Kind.CAMERA)
    today = timezone.localdate()
    if period == "today":
        photos = photos.filter(captured_at__date=today)
    elif period in {"7d", "30d"}:
        days = 7 if period == "7d" else 30
        photos = photos.filter(captured_at__gte=timezone.now() - timedelta(days=days))
    elif period == "custom":
        if date_from:
            photos = photos.filter(captured_at__date__gte=date_from)
        if date_to:
            photos = photos.filter(captured_at__date__lte=date_to)
    return photos.order_by("-captured_at", "-created_at")


@admin_required
def photo_batch_manager(request):
    filtered = _filtered_admin_photos(request.POST if request.method == "POST" else request.GET)
    if request.method == "POST":
        scope = request.POST.get("selection_scope", "selected")
        selected_ids = list(dict.fromkeys(request.POST.getlist("photo_ids")))
        try:
            selected_ids = [str(UUID(value)) for value in selected_ids]
        except (TypeError, ValueError):
            messages.error(request, "A seleção contém identificadores inválidos. Nenhuma imagem foi excluída.")
            return redirect(f"{reverse('ops-photo-batch-manager')}?{request.POST.get('return_query', '')}")
        target = filtered if scope == "filtered" else GardenPhoto.objects.filter(pk__in=selected_ids)
        target_ids = list(target.values_list("pk", flat=True))
        if scope != "filtered" and len(target_ids) != len(selected_ids):
            messages.error(request, "A seleção contém fotografias inexistentes. Nenhuma imagem foi excluída.")
            return redirect(f"{reverse('ops-photo-batch-manager')}?{request.POST.get('return_query', '')}")
        if not target_ids:
            messages.warning(request, "Nenhuma fotografia foi selecionada.")
            return redirect(f"{reverse('ops-photo-batch-manager')}?{request.POST.get('return_query', '')}")
        deleted_count = 0
        failed_count = 0
        try:
            with transaction.atomic():
                # GardenPhoto armazena os bytes no próprio banco. A exclusão do
                # registro remove a imagem persistente sem deixar arquivo órfão.
                for start in range(0, len(target_ids), 500):
                    batch = target_ids[start:start + 500]
                    result, details = GardenPhoto.objects.filter(pk__in=batch).delete()
                    deleted_count += details.get("devices.GardenPhoto", result)
        except Exception:
            failed_count = len(target_ids)
            deleted_count = 0
            logger.exception(
                "admin_photo_batch_delete_failed user_id=%s requested=%d scope=%s",
                request.user.pk, failed_count, scope,
            )
            messages.error(request, f"Nenhuma fotografia foi excluída. Falharam: {failed_count}.")
        else:
            logger.info(
                "admin_photo_batch_deleted user_id=%s deleted=%d failed=%d scope=%s",
                request.user.pk, deleted_count, failed_count, scope,
            )
            messages.success(request, f"Fotografias excluídas: {deleted_count}. Falhas: {failed_count}.")
        return redirect(f"{reverse('ops-photo-batch-manager')}?{request.POST.get('return_query', '')}")

    paginator = Paginator(filtered, 24)
    page = paginator.get_page(request.GET.get("page"))
    query_without_page = request.GET.copy()
    query_without_page.pop("page", None)
    return render(request, "admin_portal/photo_batch_manager.html", {
        "photos": page, "filtered_count": paginator.count,
        "gardens": Garden.objects.select_related("organization").order_by("organization__name", "name"),
        "cameras": Device.objects.filter(kind=Device.Kind.CAMERA).select_related("garden").order_by("name"),
        "filters": request.GET, "return_query": query_without_page.urlencode(),
    })


class ContractedCropsForm(forms.Form):
    crops = forms.ModelMultipleChoiceField(
        label="Culturas contratadas",
        queryset=Crop.objects.filter(is_available=True).order_by("common_name"),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, capacity=None, **kwargs):
        self.capacity = capacity
        super().__init__(*args, **kwargs)

    def clean_crops(self):
        crops = self.cleaned_data["crops"]
        if self.capacity and crops.count() > self.capacity:
            raise forms.ValidationError(f"Selecione no máximo {self.capacity} culturas para este modelo de horta.")
        return crops


class PlantedCropAdministrationForm(forms.ModelForm):
    position = forms.CharField(label="Posição", required=False)

    class Meta:
        model = PlantingCycle
        fields = ("cultivar", "status", "planted_at", "notes")
        labels = {"cultivar": "Cultura e variedade", "planted_at": "Data do plantio", "notes": "Observações"}
        widgets = {"planted_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "notes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["position"].initial = self.instance.module.position_label
        self.fields["cultivar"].queryset = Cultivar.objects.filter(is_active=True).select_related("crop").order_by("crop__common_name", "name")
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def save(self, commit=True):
        cycle = super().save(commit=False)
        cycle.crop = cycle.cultivar.crop
        if commit:
            cycle.save()
            position = self.cleaned_data["position"].strip()
            if cycle.module.position_label != position:
                cycle.module.position_label = position
                cycle.module.save(update_fields=["position_label", "updated_at"])
        return cycle
SECTION_AREA = {section: slug for slug, (_, _, sections) in AREAS.items() for section in sections}


@operations_required
def area_dashboard(request, area):
    if area not in AREAS:
        raise Http404
    title, description, sections = AREAS[area]
    cards = []
    for section in sections:
        resource = get_resource(section)
        cards.append({"section": section, "title": resource.title if resource else ("QR Codes" if section == "qrcodes" else "Configurações"), "count": resource.model.objects.count() if resource else None, "readonly": resource.readonly if resource else True})
    return render(request, "admin_portal/area.html", {"area": area, "title": title, "description": description, "cards": cards})


def _form_context(form, section, title, obj=None):
    links = {"inventory_category": ("inventory-categories", "Nova categoria"), "primary_supplier": ("suppliers", "Novo fornecedor"), "supplier": ("suppliers", "Novo fornecedor"), "organization": ("organizations", "Nova organização"), "plan_version": ("plan-versions", "Novo plano"), "coupon": ("coupons", "Novo cupom"), "subscription": ("subscriptions", "Nova assinatura"), "crop": ("crops", "Nova cultura"), "cultivar": ("cultivars", "Nova variedade"), "cultivation_profile": ("cultivation-profiles", "Novo perfil"), "fertilizer": ("fertilizers", "Novo fertilizante"), "material": ("substrates", "Novo material"), "module_type": ("module-types", "Novo tipo de módulo"), "garden": ("gardens", "Nova horta"), "model": ("device-models", "Novo modelo"), "metric_definition": ("metrics", "Nova métrica"), "technician": ("employees", "Novo funcionário"), "work_order": ("orders", "Nova ordem")}
    actions = {name: {"section": target, "label": label} for name, (target, label) in links.items() if name in form.fields}
    groups = [("Dados do cadastro", list(form))]
    if section == "inventory":
        spec = (("Identificação", "sku name inventory_category description"), ("Fornecimento", "primary_supplier brand"), ("Controle", "unit tracks_lots tracks_expiration"), ("Estoque", "minimum_quantity reorder_point physical_location"), ("Financeiro", "average_cost_cents reference_price_cents"), ("Status", "is_active"))
        groups = [(label, [form[name] for name in names.split() if name in form.fields]) for label, names in spec]
    elif section == "crops":
        spec = (
            ("Identificação", "image remove_image common_name scientific_name code description is_available"),
            ("Necessidades de cultivo", "water_requirement light_hours ideal_temperature_min ideal_temperature_max cultivation_guidance drainage_requirement soil_moisture_requirement"),
            ("Configurações", "irrigation_frequency_count irrigation_frequency_period pump_duration_seconds"),
        )
        groups = [(label, [form[name] for name in names.split() if name in form.fields]) for label, names in spec]
    elif section == "visits":
        spec = [("Contexto", "organization garden work_order"), ("Responsável", "technician"), ("Agendamento", "visit_type scheduled_start scheduled_end status")]
        if obj:
            spec.append(("Execução", "actual_start actual_end reason notes conclusion"))
        groups = [(label, [form[name] for name in names.split() if name in form.fields]) for label, names in spec]
    return {"title": title, "form": form, "section": section, "object": obj, "related_actions": actions, "field_groups": groups, "area": SECTION_AREA.get(section), "delete_available": bool(obj and section in DELETE_POLICIES)}


def _guided_context(form, section, resource):
    flow = get_flow(section)
    used = set()
    wizard_steps = []
    for flow_step in flow.steps:
        fields = [form[name] for name in flow_step.fields if name in form.fields]
        used.update(field.name for field in fields)
        wizard_steps.append({"step": flow_step, "fields": fields})
    remaining = [field for field in form if field.name not in used]
    if remaining:
        from .guided_flows import FlowStep
        wizard_steps.append({"step": FlowStep("Detalhes finais", "Complete as informações restantes.", "Esses dados concluem o cadastro operacional.", tuple(field.name for field in remaining)), "fields": remaining})
    base = _form_context(form, section, flow.title)
    return {**base, "flow": flow, "wizard_steps": wizard_steps, "resource": resource}


def _display_fields(obj):
    hidden = {"password", "secret_hash", "raw", "diagnostics"}
    values = []
    for field in obj._meta.fields:
        if field.name in hidden:
            continue
        value = getattr(obj, f"get_{field.name}_display", lambda: getattr(obj, field.name))()
        label = field.verbose_name.capitalize()
        if isinstance(obj, Device) and field.name == "status":
            label = "Estado cadastral"
        elif isinstance(obj, Device) and field.name == "last_seen_at":
            label = "Último contato"
        values.append((label, value if value not in (None, "") else "—"))
        if isinstance(obj, Device) and field.name == "status":
            values.append(("Conectividade", "Online" if obj.is_online else "Offline"))
    return values


@operations_required
def dashboard(request):
    today = timezone.localdate()
    now = timezone.now()
    cards = [
        ("Clientes ativos", Organization.objects.filter(is_active=True).count(), "clients"),
        ("Hortas instaladas", Garden.objects.filter(is_active=True, status=Garden.Status.INSTALLED).count(), "gardens"),
        ("Hortas offline", Garden.objects.filter(is_active=True).filter(Q(devices__last_seen_at__lt=now - timedelta(seconds=settings.DEVICE_ONLINE_THRESHOLD_SECONDS)) | Q(devices__last_seen_at__isnull=True)).distinct().count(), "gardens"),
        ("Visitas hoje", Visit.objects.filter(scheduled_start__date=today).count(), "visits"),
        ("Estoque abaixo do mínimo", InventoryItem.objects.filter(quantity__lt=F("minimum_quantity"), is_active=True).count(), "inventory"),
        ("Chamados abertos", SupportTicket.objects.exclude(status=SupportTicket.Status.RESOLVED).count(), "tickets"),
    ]
    visits = Visit.objects.filter(scheduled_start__date=today).select_related("organization", "technician")[:8]
    alerts = Alert.objects.filter(status=Alert.Status.OPEN).select_related("rule", "rule__channel__device").order_by("-rule__severity")[:8]
    return render(request, "admin_portal/dashboard.html", {"cards": cards, "visits": visits, "alerts": alerts, "primary_actions": PRIMARY_ACTIONS, "demo_seed_enabled": settings.ENABLE_DEMO_SEED})


@operations_required
def collection(request, section):
    if section == "plans":
        return redirect("ops-plan-management")
    resource = get_resource(section)
    if not resource:
        if section == "qrcodes":
            return render(request, "admin_portal/collection.html", {"title": "QR Codes", "section": section, "objects": GardenModule.objects.select_related("organization").order_by("name")})
        if section in {"reports", "settings"}:
            return render(request, "admin_portal/collection.html", {"title": section.title(), "section": section, "objects": []})
        raise Http404
    if section == "clients":
        query = request.GET.get("q", "").strip()
        queryset = User.objects.filter(memberships__role__in=[Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.VIEWER]).distinct().order_by("full_name")
        if query:
            queryset = queryset.filter(Q(full_name__icontains=query) | Q(email__icontains=query) | Q(memberships__organization__name__icontains=query)).distinct()
        page = Paginator(queryset, 25).get_page(request.GET.get("page"))
        return render(request, "admin_portal/collection.html", {"title": "Clientes", "section": section, "area": "comercial", "page_obj": page, "objects": page.object_list, "query": query, "resource": resource})
    queryset = resource.model.objects.all().order_by(*resource.ordering)
    if section == "crops":
        queryset = queryset.filter(code__in=("alface", "tomilho", "coentro")).annotate(
            variety_count=Count("cultivars", distinct=True),
            active_cycle_count=Count("planting_cycles", filter=Q(planting_cycles__status=PlantingCycle.Status.ACTIVE), distinct=True),
            history_count=Count("planting_cycles", distinct=True),
        ).order_by("common_name")
    if section == "employees":
        queryset = queryset.filter(employee_role__isnull=False).distinct()
    query = request.GET.get("q", "").strip()
    if query and resource.search:
        condition = Q()
        for field in resource.search:
            condition |= Q(**{f"{field}__icontains": query})
        queryset = queryset.filter(condition)
    status = request.GET.get("status", "").strip()
    if section == "crops" and status in {"active", "inactive"}:
        queryset = queryset.filter(is_available=status == "active")
    elif status and any(field.name == "status" for field in resource.model._meta.fields):
        queryset = queryset.filter(status=status)
    variety = request.GET.get("variety", "").strip()
    if section == "crops" and variety in {"with", "without"}:
        queryset = queryset.filter(cultivars__isnull=variety == "without").distinct()
    organization = request.GET.get("organization", "").strip()
    field_names = {field.name for field in resource.model._meta.fields}
    if organization and "organization" in field_names:
        queryset = queryset.filter(organization_id=organization)
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    if section == "crops":
        return render(request, "admin_portal/crop_collection.html", {
            "title": resource.title, "section": section, "area": SECTION_AREA.get(section),
            "page_obj": page, "objects": page.object_list, "query": query, "resource": resource,
        })
    return render(request, "admin_portal/collection.html", {"title": resource.title, "section": section, "area": SECTION_AREA.get(section), "page_obj": page, "objects": page.object_list, "query": query, "resource": resource, "organizations": Organization.objects.filter(is_active=True).order_by("name")})


@operations_required
def detail(request, section, pk):
    if section == "plans":
        return redirect("ops-plan-detail", plan_id=pk)
    resource = get_resource(section)
    if not resource:
        raise Http404
    obj = get_object_or_404(resource.model, pk=pk)
    context = {"title": resource.title, "section": section, "object": obj, "display_fields": _display_fields(obj), "resource": resource, "delete_available": section in DELETE_POLICIES}
    if section == "crops":
        context.update({
            "varieties": obj.cultivars.order_by("name"),
            "profiles": obj.cultivation_profiles.prefetch_related("stages").order_by("name"),
            "nutrition_plans": obj.nutrition_plans.select_related("fertilizer"),
            "cycles": obj.planting_cycles.select_related("cultivar", "module").order_by("-created_at")[:25],
        })
    return render(request, "admin_portal/detail.html", context)


@operations_required
def create(request, section):
    if section == "plans":
        return redirect("ops-plan-create")
    resource = get_resource(section)
    if not resource or resource.readonly or section == "credentials":
        raise Http404
    if section in {"crops", "crop-lighting", "garden-models"} and not request.user.is_hortaviva_admin:
        raise PermissionDenied
    form = resource_form_class(resource)(request.POST or None, request.FILES or None)
    feature_formset = GardenModelFeatureFormSet(request.POST or None, prefix="features") if section == "garden-models" else None
    form.feature_formset = feature_formset
    if request.method == "POST" and form.is_valid() and (feature_formset is None or feature_formset.is_valid()):
        if isinstance(form.instance, CropLightingSchedule):
            form.instance.updated_by = request.user
        with transaction.atomic():
            obj = run_guided_workflow(section, form)
            if feature_formset is not None:
                feature_formset.instance = obj
                feature_formset.save()
        messages.success(request, "Registro criado com sucesso.")
        return redirect("ops-detail", section=section, pk=obj.pk)
    flow = get_flow(section)
    if flow:
        return render(request, "admin_portal/guided_form.html", _guided_context(form, section, resource))
    return render(request, "admin_portal/form.html", _form_context(form, section, f"Novo — {resource.title}"))


@operations_required
def edit(request, section, pk):
    if section == "plans":
        return redirect("ops-plan-edit", plan_id=pk)
    resource = get_resource(section)
    if not resource or resource.readonly:
        raise Http404
    if section in {"crops", "crop-lighting", "garden-models"} and not request.user.is_hortaviva_admin:
        raise PermissionDenied
    obj = get_object_or_404(resource.model, pk=pk)
    form = resource_form_class(resource)(request.POST or None, request.FILES or None, instance=obj)
    feature_formset = GardenModelFeatureFormSet(request.POST or None, instance=obj, prefix="features") if section == "garden-models" else None
    form.feature_formset = feature_formset
    if request.method == "POST" and form.is_valid() and (feature_formset is None or feature_formset.is_valid()):
        if isinstance(form.instance, CropLightingSchedule):
            form.instance.updated_by = request.user
        with transaction.atomic():
            form.save()
            if feature_formset is not None:
                feature_formset.save()
        if section == "crops" and getattr(form, "active_cycle_count", 0):
            messages.warning(request, f"Esta cultura possui {form.active_cycle_count} cultivo(s) ativo(s). Ela deixou de aparecer para novas escolhas, mas os cultivos existentes continuam funcionando.")
        messages.success(request, "Alterações salvas.")
        return redirect("ops-detail", section=section, pk=obj.pk)
    return render(request, "admin_portal/form.html", _form_context(form, section, f"Editar — {resource.title}", obj))


@operations_required
def client_create(request):
    form = ClientOnboardingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = create_customer(form)
        messages.success(request, "Cliente, organização e vínculos criados com sucesso.")
        return redirect("ops-client-detail", user_id=user.pk)
    resource = get_resource("clients")
    return render(request, "admin_portal/guided_form.html", _guided_context(form, "clients", resource))


@operations_required
def client_detail(request, user_id):
    user = get_object_or_404(User, pk=user_id, memberships__role__in=[Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.VIEWER])
    memberships = user.memberships.select_related("organization")
    organizations = Organization.objects.filter(memberships__user=user).distinct()
    organization = organizations.order_by("-is_active", "name").first()
    if not organization:
        raise Http404
    subscriptions = organization.subscriptions.select_related("plan_version__plan", "coupon").order_by("-created_at")
    gardens = organization.gardens.select_related("address", "garden_model", "primary_technician", "subscription__plan_version__plan__garden_model").order_by("name")
    visits = organization.visits.select_related("garden", "technician").order_by("-scheduled_start")
    tickets = organization.support_tickets.select_related("garden", "module", "device").order_by("-created_at")
    active_subscription = subscriptions.filter(status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIALING]).first()
    next_visit = visits.filter(scheduled_start__gte=timezone.now(), status=Visit.Status.SCHEDULED).order_by("scheduled_start").first()
    address = organization.addresses.first()
    garden_panels = []
    for garden in gardens:
        snapshot = garden_snapshot(garden)
        camera = snapshot["camera"]
        camera_stream_url = None
        if camera and camera.local_ip:
            host = f"[{camera.local_ip}]" if ":" in camera.local_ip else camera.local_ip
            camera_stream_url = f"http://{host}/stream"
        config = effective_garden_configuration(garden)
        automation_panel = automation_panel_context(
            user=request.user, garden=garden, snapshot=snapshot,
            next_url=request.get_full_path(),
        )
        lighting_schedule = None
        if snapshot["light_channel"]:
            lighting_schedule = snapshot["light_channel"].lighting_schedules.filter(enabled=True).first()
        irrigation = config.get("irrigation", {}) if isinstance(config.get("irrigation"), Mapping) else {}
        irrigation_duration = irrigation.get("pump_duration_seconds")
        if irrigation_duration is None:
            irrigation_duration = irrigation.get("duration_seconds")
        planted_crops = []
        for cycle in snapshot["cycles"]:
            crop = cycle.crop or (cycle.cultivar.crop if cycle.cultivar_id else None)
            planted_crops.append({
                "cycle": cycle,
                "name": crop.common_name if crop else "Cultura não definida",
                "position": cycle.module.position_label or "Posição não informada",
            })
        garden_panels.append({
            "garden": garden,
            "snapshot": snapshot,
            "camera_stream_url": camera_stream_url,
            "configuration": config,
            "automation_panel": automation_panel,
            "irrigation": irrigation,
            "irrigation_duration": irrigation_duration,
            "lighting": config.get("lighting", {}) if isinstance(config.get("lighting"), Mapping) else {},
            "lighting_schedule": lighting_schedule,
            "planted_crops": planted_crops,
            "configuration_origins": {
                section: "Personalizado" if isinstance(garden.automation_overrides, dict) and section in garden.automation_overrides else "Padrão HortaViva"
                for section in ("irrigation", "lighting", "camera", "monitoring")
            },
            "has_operational_overrides": bool(
                isinstance(garden.automation_overrides, dict)
                and {"irrigation", "lighting", "camera", "monitoring"}.intersection(garden.automation_overrides)
            ),
        })
    allowed_tabs = {"resumo", "dados", "subscriptions", "gardens", "reports", "visits", "tickets"}
    active_tab = request.GET.get("aba", "resumo")
    if active_tab not in allowed_tabs:
        active_tab = "resumo"
    client = user
    return render(request, "admin_portal/client_detail.html", locals())


def _client_for_garden(garden):
    return User.objects.filter(
        memberships__organization=garden.organization,
        memberships__role__in=[Membership.Role.OWNER, Membership.Role.MANAGER],
        memberships__is_active=True,
    ).order_by("memberships__role", "id").first()


def _current_checkout(garden):
    if not garden.subscription_id:
        return None
    return CheckoutRequest.objects.filter(
        user__memberships__organization=garden.organization,
        plan_version=garden.subscription.plan_version,
        status=CheckoutRequest.Status.CONFIRMED,
    ).prefetch_related("selected_crops").order_by("-created_at").first()


@admin_required
def garden_admin_edit(request, garden_id):
    garden = get_object_or_404(Garden.objects.select_related("organization"), pk=garden_id)
    form = GardenAdministrationForm(request.POST or None, instance=garden, organization=garden.organization)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Horta atualizada com sucesso.")
        client = _client_for_garden(garden)
        return redirect(f"{reverse('ops-client-detail', args=[client.pk])}?aba=gardens") if client else redirect("ops-detail", section="gardens", pk=garden.pk)
    return render(request, "admin_portal/form.html", _form_context(form, "gardens", f"Editar horta — {garden.name}", garden))


@admin_required
@require_POST
def garden_mark_installed(request, garden_id):
    garden = get_object_or_404(Garden, pk=garden_id)
    if garden.status != Garden.Status.INSTALLED:
        garden.status = Garden.Status.INSTALLED
        if not garden.installed_at:
            garden.installed_at = timezone.now()
        garden.save(update_fields=["status", "installed_at", "updated_at"])
        messages.success(request, "Horta marcada como instalada.")
    client = _client_for_garden(garden)
    return redirect(f"{reverse('ops-client-detail', args=[client.pk])}?aba=gardens") if client else redirect("ops-detail", section="gardens", pk=garden.pk)


@admin_required
def garden_cultures(request, garden_id):
    garden = get_object_or_404(Garden.objects.select_related("organization", "garden_model"), pk=garden_id)
    cycles = garden.planting_cycles.select_related("crop", "cultivar__crop", "module").order_by("-created_at")
    checkout = _current_checkout(garden)
    client = _client_for_garden(garden)
    return render(request, "admin_portal/garden_cultures.html", {"garden": garden, "cycles": cycles, "checkout": checkout, "client": client})


@admin_required
def garden_crop_edit(request, garden_id, cycle_id):
    garden = get_object_or_404(Garden, pk=garden_id)
    cycle = get_object_or_404(PlantingCycle.objects.select_related("module", "cultivar__crop"), pk=cycle_id, garden=garden)
    form = PlantedCropAdministrationForm(request.POST or None, instance=cycle)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cultura plantada atualizada.")
        return redirect("ops-garden-cultures", garden_id=garden.pk)
    return render(request, "admin_portal/form.html", _form_context(form, "cycles", f"Alterar cultura — {garden.name}", cycle))


@admin_required
def garden_contracted_crops(request, garden_id):
    garden = get_object_or_404(Garden.objects.select_related("garden_model"), pk=garden_id)
    checkout = _current_checkout(garden)
    if not checkout:
        messages.error(request, "Não há checkout confirmado para editar as culturas contratadas.")
        return redirect("ops-garden-cultures", garden_id=garden.pk)
    capacity = garden.garden_model.capacity if garden.garden_model_id else None
    form = ContractedCropsForm(request.POST or None, capacity=capacity, initial={"crops": checkout.selected_crops.all()})
    if request.method == "POST" and form.is_valid():
        checkout.selected_crops.set(form.cleaned_data["crops"])
        messages.success(request, "Culturas contratadas atualizadas sem alterar os cultivos plantados.")
        return redirect("ops-garden-cultures", garden_id=garden.pk)
    return render(request, "admin_portal/form.html", _form_context(form, "crops", f"Editar culturas contratadas — {garden.name}"))


@admin_required
def garden_devices(request, garden_id):
    garden = get_object_or_404(Garden.objects.select_related("organization"), pk=garden_id)
    assigned = garden.devices.select_related("model").order_by("kind", "name")
    available = Device.objects.filter(organization=garden.organization, garden__isnull=True).select_related("model").order_by("name")
    return render(request, "admin_portal/garden_devices.html", {"garden": garden, "assigned": assigned, "available": available})


@operations_required
def client_edit(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    form = ClientOnboardingForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cliente atualizado.")
        return redirect("ops-client-detail", user_id=user.pk)
    return render(request, "admin_portal/form.html", _form_context(form, "clients", "Editar cliente", user))


@admin_required
def client_delete(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    summary = customer_deletion_summary(user)
    if request.method == "POST":
        if request.POST.get("confirmation", "").strip() != "EXCLUIR":
            messages.error(request, "Digite EXCLUIR para confirmar a exclusão completa.")
        else:
            name = user.full_name or user.email
            try:
                delete_customer_completely(user)
            except DeletionBlocked as error:
                messages.error(request, error.message)
            else:
                messages.success(request, f"Cliente {name} e seus dados de teste foram excluídos.")
                return redirect("ops-collection", section="clients")
    return render(request, "admin_portal/delete_confirm.html", {
        "object": user, "record_name": user.full_name or user.email, "record_type": "Cliente",
        "summary": summary, "strong_confirmation": True,
        "warning": "O cliente, suas organizações e todos os dados vinculados serão removidos permanentemente.",
    })


@admin_required
def administrative_delete(request, section, pk):
    if section not in DELETE_POLICIES:
        raise Http404
    resource = get_resource(section)
    obj = get_object_or_404(resource.model, pk=pk)
    summary = object_deletion_summary(section, obj)
    strong = requires_strong_confirmation(section, summary)
    allow_deactivate = can_deactivate(section, summary)
    if request.method == "POST":
        action = request.POST.get("action", "delete")
        if action == "deactivate" and allow_deactivate:
            deactivate_object(section, obj)
            messages.success(request, f"{DELETE_POLICIES[section].label} desativado com sucesso.")
            return redirect("ops-detail", section=section, pk=obj.pk)
        if strong and request.POST.get("confirmation", "").strip() != "EXCLUIR":
            messages.error(request, "Digite EXCLUIR para confirmar a exclusão.")
        else:
            try:
                delete_administrative_object(section, obj)
            except DeletionBlocked as error:
                messages.error(request, error.message)
            else:
                messages.success(request, f"{DELETE_POLICIES[section].label} excluído com sucesso.")
                return redirect("ops-collection", section=section)
    return render(request, "admin_portal/delete_confirm.html", {
        "object": obj, "record_name": str(obj), "record_type": DELETE_POLICIES[section].label,
        "summary": summary, "strong_confirmation": strong, "allow_deactivate": allow_deactivate,
        "warning": "Esta ação é irreversível e remove permanentemente o cadastro e os dados explicitamente relacionados.",
    })


CLIENT_SECTIONS = {"subscriptions": "Nova assinatura", "gardens": "Nova horta", "modules": "Novo módulo", "cycles": "Novo cultivo", "devices": "Novo dispositivo", "visits": "Nova visita", "payments": "Novo pagamento", "tickets": "Novo chamado"}


@operations_required
def client_related_create(request, user_id, section):
    if section not in CLIENT_SECTIONS:
        raise Http404
    user = get_object_or_404(User, pk=user_id)
    organization = Organization.objects.filter(memberships__user=user, memberships__is_active=True).order_by("-is_active", "name").first()
    if not organization:
        raise Http404
    resource = get_resource(section)
    data = request.POST.copy() if request.method == "POST" else None
    if data is not None and "organization" in resource.fields:
        data["organization"] = str(organization.pk)
    form = CustomerModuleForm(data, organization=organization) if section == "modules" else resource_form_class(resource)(data)
    form.customer_organization_id = organization.pk
    if "organization" in form.fields:
        form.fields["organization"].initial = organization
        form.fields["organization"].widget = forms.HiddenInput()
    if "plan_version" in form.fields:
        form.fields["plan_version"].label = "Plano"
        form.fields["plan_version"].label_from_instance = lambda version: f"{version.plan.name} — R$ {version.price_cents / 100:.2f}"
    scoped = {"address": organization.addresses.all(), "subscription": organization.subscriptions.all(), "garden": organization.gardens.all(), "module": organization.garden_modules.all(), "device": organization.devices.all(), "work_order": organization.work_orders.all()}
    for name, queryset in scoped.items():
        if name in form.fields:
            form.fields[name].queryset = queryset
    if request.method == "POST" and form.is_valid():
        run_guided_workflow(section, form)
        messages.success(request, f"Cadastro criado com sucesso para {user.full_name}.")
        return redirect(f"{reverse('ops-client-detail', args=[user.pk])}?aba={section}")
    context = _guided_context(form, section, resource) if get_flow(section) else _form_context(form, section, CLIENT_SECTIONS[section])
    context.update({"client_context": user, "client_organization": organization, "has_customer_gardens": organization.gardens.filter(is_active=True).exists()})
    return render(request, "admin_portal/guided_form.html" if get_flow(section) else "admin_portal/form.html", context)


@operations_required
def client_module_install(request, user_id, module_id):
    user = get_object_or_404(User, pk=user_id)
    organization = Organization.objects.filter(memberships__user=user, memberships__is_active=True).order_by("-is_active", "name").first()
    if not organization:
        raise Http404
    module = get_object_or_404(GardenModule, pk=module_id, organization=organization)
    form = CustomerModuleInstallationForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            install_module(module, form.cleaned_data["garden"], form.cleaned_data["installed_at"], form.cleaned_data["position_label"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "Módulo instalado com sucesso. Próxima etapa recomendada: iniciar cultivo ou adicionar dispositivo.")
            return redirect(f"{reverse('ops-client-detail', args=[user.pk])}?aba=modules")
    return render(request, "admin_portal/form.html", _form_context(form, "modules", f"Instalar {module.name}", module))


@operations_required
@require_POST
def credential_issue(request, device_id):
    device = get_object_or_404(Device, pk=device_id)
    credential, token = DeviceCredential.issue(device, name=request.POST.get("name", "principal"))
    return render(request, "admin_portal/credential_created.html", {"device": device, "credential": credential, "token": token})


@operations_required
@require_POST
def credential_revoke(request, pk):
    credential = get_object_or_404(DeviceCredential, pk=pk)
    credential.is_active = False
    credential.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "Credencial revogada.")
    return redirect("ops-detail", section="devices", pk=credential.device_id)


@operations_required
@require_POST
def create_demo(request):
    if not request.user.is_superuser or not settings.ENABLE_DEMO_SEED:
        raise Http404
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        messages.error(request, "DEMO_PASSWORD não está configurada.")
        return redirect("ops-dashboard")
    call_command("seed_demo", password=password, verbosity=0)
    messages.success(request, "Dados de demonstração criados ou atualizados.")
    return redirect("ops-dashboard")


@operations_required
def module_qr(request, module_id):
    import qrcode
    module = get_object_or_404(GardenModule, pk=module_id)
    payload = f"hortaviva:module:{module.pk}"
    image = qrcode.make(payload)
    output = BytesIO()
    image.save(output, format="PNG")
    if request.GET.get("download") == "1":
        response = HttpResponse(output.getvalue(), content_type="image/png")
        response["Content-Disposition"] = f'attachment; filename="modulo-{module.serial_number}.png"'
        return response
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return render(request, "admin_portal/module_qr.html", {"module": module, "qr_data": encoded, "payload": payload})
