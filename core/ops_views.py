import os
import base64
from datetime import timedelta
from io import BytesIO

from django.conf import settings
from django import forms
from collections.abc import Mapping
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Membership, Organization, User
from crops.models import Crop, Cultivar, PlantingCycle
from devices.models import Alert, Device, DeviceCredential
from gardens.models import Garden, GardenModule, ModuleInstallation
from gardens.selectors import get_active_installations
from gardens.configuration import effective_garden_configuration
from devices.selectors import garden_snapshot
from operations.models import InventoryItem, SupportTicket, Visit, WorkOrder
from subscriptions.models import CheckoutRequest, Payment, Plan, Subscription

from .backoffice import get_resource
from .backoffice_forms import ClientOnboardingForm, CustomerModuleForm, CustomerModuleInstallationForm, resource_form_class
from gardens.services import install_module
from .guided_flows import PRIMARY_ACTIONS, get_flow
from .workflow_services import create_customer, run_guided_workflow
from .permissions import admin_required, operations_required
from .deletion_services import (
    DELETE_POLICIES, DeletionBlocked, can_deactivate, customer_deletion_summary,
    deactivate_object, delete_administrative_object, delete_customer_completely,
    object_deletion_summary, requires_strong_confirmation,
)


AREAS = {
    "comercial": ("Clientes", "Clientes da HortaViva.", ("clients",)),
    "configuracoes": ("Planos e assinaturas", "Configurações comerciais dos modelos de horta.", ("plans", "subscriptions")),
    "cultivo": ("Cultivo", "Catálogo agronômico, ciclos, colheitas e insumos.", ("crops", "cultivars", "cultivation-profiles", "crop-stages", "cycles", "harvests", "substrates", "substrate-recipes", "fertilizers", "nutrition-plans")),
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
        queryset = queryset.annotate(
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
    return render(request, "admin_portal/collection.html", {"title": resource.title, "section": section, "area": SECTION_AREA.get(section), "page_obj": page, "objects": page.object_list, "query": query, "resource": resource, "organizations": Organization.objects.filter(is_active=True).order_by("name")})


@operations_required
def detail(request, section, pk):
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
    resource = get_resource(section)
    if not resource or resource.readonly or section == "credentials":
        raise Http404
    form = resource_form_class(resource)(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = run_guided_workflow(section, form)
        messages.success(request, "Registro criado com sucesso.")
        return redirect("ops-detail", section=section, pk=obj.pk)
    flow = get_flow(section)
    if flow:
        return render(request, "admin_portal/guided_form.html", _guided_context(form, section, resource))
    return render(request, "admin_portal/form.html", _form_context(form, section, f"Novo — {resource.title}"))


@operations_required
def edit(request, section, pk):
    resource = get_resource(section)
    if not resource or resource.readonly:
        raise Http404
    obj = get_object_or_404(resource.model, pk=pk)
    form = resource_form_class(resource)(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
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
        config = effective_garden_configuration(garden)
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
            "configuration": config,
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
    DeviceCredential.objects.filter(device=device, is_active=True).update(is_active=False)
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
