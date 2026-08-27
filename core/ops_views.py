import os
import base64
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Membership, Organization, User
from crops.models import Crop, PlantingCycle
from devices.models import Alert, Device, DeviceCredential
from gardens.models import Garden, GardenModule
from operations.models import SupportTicket, Visit, WorkOrder
from subscriptions.models import Payment, Plan, Subscription

from .backoffice import get_resource
from .backoffice_forms import ClientOnboardingForm, resource_form_class
from .guided_flows import PRIMARY_ACTIONS, get_flow
from .workflow_services import create_customer, run_guided_workflow
from .permissions import operations_required


AREAS = {
    "comercial": ("Comercial", "Clientes, planos, assinaturas e faturamento.", ("clients", "organizations", "plans", "subscriptions", "coupons", "payments")),
    "cultivo": ("Cultivo", "Catálogo agronômico, ciclos, colheitas e insumos.", ("crops", "cultivars", "cultivation-profiles", "crop-stages", "cycles", "harvests", "substrates", "substrate-recipes", "fertilizers", "nutrition-plans")),
    "hortas": ("Hortas", "Estrutura instalada, módulos e instalações.", ("gardens", "module-types", "modules", "installations", "qrcodes")),
    "iot": ("IoT", "Dispositivos, métricas, telemetria e automações.", ("device-models", "devices", "metrics", "channels", "telemetry", "calibrations", "commands", "alert-rules", "alerts", "lighting")),
    "operacao": ("Operação", "Agenda, ordens, manutenção e atendimento.", ("visits", "orders", "maintenance", "maintenance-records", "tickets")),
    "estoque": ("Estoque", "Itens, categorias, fornecedores, lotes e movimentações.", ("inventory", "inventory-categories", "suppliers", "stock-lots", "stock-movements")),
    "administracao": ("Administração", "Equipe e configurações operacionais.", ("employees", "settings")),
}
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
    return {"title": title, "form": form, "section": section, "object": obj, "related_actions": actions, "field_groups": groups, "area": SECTION_AREA.get(section)}


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
        values.append((field.verbose_name.capitalize(), value if value not in (None, "") else "—"))
    return values


@operations_required
def dashboard(request):
    today = timezone.localdate()
    now = timezone.now()
    cards = [
        ("Planos ativos sem preço vigente", Plan.objects.filter(is_active=True).exclude(versions__retired_at__isnull=True).distinct().count(), "plans"),
        ("Culturas disponíveis sem perfil", Crop.objects.filter(is_available=True, cultivation_profiles__isnull=True).count(), "crops"),
        ("Módulos instalados sem ciclo", GardenModule.objects.filter(status=GardenModule.Status.INSTALLED, planting_cycles__isnull=True).count(), "modules"),
        ("Clientes ativos", Organization.objects.filter(is_active=True).count(), "clients"),
        ("Organizações", Organization.objects.count(), "organizations"),
        ("Assinaturas ativas", Subscription.objects.filter(status=Subscription.Status.ACTIVE).count(), "subscriptions"),
        ("Inadimplentes", Subscription.objects.filter(status=Subscription.Status.PAST_DUE).count(), "subscriptions"),
        ("Hortas", Garden.objects.filter(is_active=True).count(), "gardens"),
        ("Módulos instalados", GardenModule.objects.filter(status=GardenModule.Status.INSTALLED).count(), "modules"),
        ("Módulos disponíveis", GardenModule.objects.filter(status=GardenModule.Status.STOCK).count(), "modules"),
        ("Dispositivos online", Device.objects.filter(status=Device.Status.ONLINE).count(), "devices"),
        ("Dispositivos offline", Device.objects.filter(status=Device.Status.OFFLINE).count(), "devices"),
        ("Culturas ativas", PlantingCycle.objects.filter(status=PlantingCycle.Status.ACTIVE).count(), "cycles"),
        ("Visitas hoje", Visit.objects.filter(scheduled_start__date=today).count(), "visits"),
        ("Próximas visitas", Visit.objects.filter(scheduled_start__gt=now, status=Visit.Status.SCHEDULED).count(), "visits"),
        ("Ordens abertas", WorkOrder.objects.exclude(status__in=[WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELED]).count(), "orders"),
        ("Ordens atrasadas", WorkOrder.objects.filter(scheduled_for__lt=now).exclude(status__in=[WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELED]).count(), "orders"),
        ("Alertas técnicos", Alert.objects.filter(status=Alert.Status.OPEN).count(), "alerts"),
        ("Pagamentos", Payment.objects.count(), "payments"),
        ("Chamados", SupportTicket.objects.exclude(status=SupportTicket.Status.RESOLVED).count(), "tickets"),
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
    if section == "employees":
        queryset = queryset.filter(Q(is_staff=True) | Q(memberships__role=Membership.Role.TECHNICIAN)).distinct()
    query = request.GET.get("q", "").strip()
    if query and resource.search:
        condition = Q()
        for field in resource.search:
            condition |= Q(**{f"{field}__icontains": query})
        queryset = queryset.filter(condition)
    status = request.GET.get("status", "").strip()
    if status and any(field.name == "status" for field in resource.model._meta.fields):
        queryset = queryset.filter(status=status)
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
    return render(request, "admin_portal/detail.html", {"title": resource.title, "section": section, "object": obj, "display_fields": _display_fields(obj), "resource": resource})


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
    return render(request, "admin_portal/client_detail.html", {"client": user, "memberships": memberships, "organizations": organizations})


@operations_required
def client_edit(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    form = ClientOnboardingForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Cliente atualizado.")
        return redirect("ops-client-detail", user_id=user.pk)
    return render(request, "admin_portal/form.html", {"title": "Editar cliente", "form": form, "section": "clients", "object": user})


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
