from datetime import timedelta
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncHour
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Address, Membership, Organization, User
from crops.models import Crop, Cultivar, PlantingCycle
from devices.models import Alert, Channel, Device, DeviceCommand, LightingSchedule, TelemetryReading
from gardens.models import Garden, GardenModule, ModuleInstallation
from operations.models import ChecklistExecution, InventoryItem, SupportTicket, Visit, WorkOrder
from subscriptions.models import CheckoutRequest, Payment, Plan, PlanVersion, Subscription
from .forms import CheckoutAddressForm, InstallationDateForm, InstallationSurveyForm, LightingScheduleForm, ProfileForm, SignupForm, SupportTicketForm, WorkOrderForm
from .permissions import customer_required, operations_required, technician_required


def home(request):
    return render(request, "public/home.html", {"plans": PlanVersion.objects.filter(plan__is_active=True).select_related("plan").order_by("price_cents")[:3], "crops": Crop.objects.filter(is_available=True)[:3]})


def public_page(request, page):
    if page not in {"how-it-works", "about", "faq", "contact"}: raise Http404
    if request.method == "POST" and page == "contact":
        messages.success(request, "Mensagem recebida. Nossa equipe entrará em contato em breve.")
        return redirect("contact")
    return render(request, f"public/{page}.html")


def plans(request):
    return render(request, "public/plans.html", {"plans": PlanVersion.objects.filter(plan__is_active=True, retired_at__isnull=True).select_related("plan").prefetch_related("features")})


def crop_catalog(request):
    return render(request, "public/crops.html", {"crops": Crop.objects.all().prefetch_related("cultivars")})


def crop_detail(request, code):
    return render(request, "public/crop_detail.html", {"crop": get_object_or_404(Crop.objects.prefetch_related("cultivars__requirements"), code=code)})


def signup(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(); login(request, user)
        next_url = request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("checkout", step=1)
    return render(request, "registration/signup.html", {"form": form, "next": request.GET.get("next", "")})


@login_required
def post_login(request):
    if request.user.is_staff: return redirect("ops-dashboard")
    memberships = request.user.memberships.filter(is_active=True).order_by("created_at", "id")
    customer = memberships.filter(role__in=[Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.VIEWER]).first()
    technician = memberships.filter(role=Membership.Role.TECHNICIAN).first()
    if customer:
        request.session["active_organization_id"] = str(customer.organization_id)
        return redirect("customer-dashboard")
    if technician:
        request.session["active_organization_id"] = str(technician.organization_id)
        return redirect("tech-dashboard")
    if request.session.get("checkout", {}).get("plan"):
        return redirect("checkout", step=2)
    return render(request, "registration/account_pending.html")


def _plan_module_limit(plan_version):
    feature = plan_version.features.filter(Q(key="modules") | Q(key__icontains="módulo")).order_by("created_at").first()
    return feature.limit if feature and feature.limit is not None else None


def _checkout_missing_step(state, plan=None):
    if not plan: return 1
    if not state.get("cultures"): return 2
    if not state.get("address"): return 3
    if not state.get("survey"): return 4
    if not state.get("scheduled_for"): return 5
    if not state.get("payment"): return 6
    return None


def checkout(request, step):
    if step not in range(1, 8): raise Http404
    state = request.session.get("checkout", {})
    available_plans = PlanVersion.objects.filter(plan__is_active=True, retired_at__isnull=True).select_related("plan").prefetch_related("features")
    selected_plan = available_plans.filter(id=state.get("plan")).first()
    missing_step = _checkout_missing_step(state, selected_plan)
    if step > 1 and (not selected_plan or (missing_step and missing_step < step)):
        messages.warning(request, "Complete a etapa anterior para continuar.")
        return redirect("checkout", step=missing_step or 1)
    form = None
    if step == 1 and request.method == "POST":
        selected_plan = available_plans.filter(id=request.POST.get("plan")).first()
        if not selected_plan:
            messages.error(request, "Escolha um plano disponível para continuar.")
        else:
            state = {"plan": str(selected_plan.id)}
            request.session["checkout"] = state
            if not request.user.is_authenticated:
                return redirect(f"{reverse('signup')}?next={reverse('checkout', args=[2])}")
            return redirect("checkout", step=2)
    elif step == 2 and request.method == "POST":
        culture_ids = request.POST.getlist("cultures")
        valid_ids = list(Cultivar.objects.filter(id__in=culture_ids, crop__is_available=True).values_list("id", flat=True))
        limit = _plan_module_limit(selected_plan)
        if not valid_ids:
            messages.error(request, "Escolha pelo menos uma cultura.")
        elif len(valid_ids) != len(set(culture_ids)):
            messages.error(request, "Uma das culturas selecionadas não está disponível.")
        elif limit is not None and len(valid_ids) > limit:
            messages.error(request, f"Este plano permite até {limit} culturas iniciais.")
        else:
            state["cultures"] = [str(value) for value in valid_ids]
    elif step == 3:
        form = CheckoutAddressForm(request.POST or None, initial=state.get("address"))
        if request.method == "POST" and form.is_valid(): state["address"] = form.cleaned_data
    elif step == 4:
        form = InstallationSurveyForm(request.POST or None, initial=state.get("survey"))
        if request.method == "POST" and form.is_valid(): state["survey"] = form.cleaned_data
    elif step == 5:
        form = InstallationDateForm(request.POST or None)
        if request.method == "POST" and form.is_valid(): state["scheduled_for"] = form.cleaned_data["scheduled_for"].isoformat()
    elif step == 6 and request.method == "POST": state["payment"] = "simulated-approved"
    if request.method == "POST" and step != 1 and (form is None or form.is_valid()):
        next_missing_step = _checkout_missing_step(state, selected_plan)
        if next_missing_step is None or next_missing_step > step:
            request.session["checkout"] = state
            return redirect("checkout", step=min(step + 1, 7))
    selected_cultures = Cultivar.objects.filter(id__in=state.get("cultures", [])).select_related("crop")
    return render(request, "public/checkout.html", {"step": step, "state": state, "plans": available_plans, "cultivars": Cultivar.objects.filter(crop__is_available=True).select_related("crop"), "form": form, "selected_plan": selected_plan, "selected_cultures": selected_cultures, "module_limit": _plan_module_limit(selected_plan) if selected_plan else None})


@login_required
@require_POST
@transaction.atomic
def checkout_complete(request):
    state = request.session.get("checkout", {})
    plan = PlanVersion.objects.select_for_update().filter(id=state.get("plan"), plan__is_active=True, retired_at__isnull=True).select_related("plan").prefetch_related("features").first()
    missing_step = _checkout_missing_step(state, plan)
    if missing_step:
        messages.error(request, "Seu checkout está incompleto. Revise as etapas antes de confirmar.")
        return redirect("checkout", step=missing_step)
    culture_ids = state.get("cultures", [])
    valid_cultures = Cultivar.objects.filter(id__in=culture_ids, crop__is_available=True)
    limit = _plan_module_limit(plan)
    if valid_cultures.count() != len(set(culture_ids)) or (limit is not None and valid_cultures.count() > limit):
        messages.error(request, "Revise as culturas selecionadas.")
        return redirect("checkout", step=2)
    membership = request.user.memberships.filter(is_active=True, role__in=[Membership.Role.OWNER, Membership.Role.MANAGER]).select_related("organization").order_by("created_at").first()
    org = membership.organization if membership else None
    if not org:
        org, _ = Organization.objects.get_or_create(slug=f"cliente-{str(request.user.id)[:8]}", defaults={"name": request.user.full_name or request.user.email})
    Membership.objects.get_or_create(user=request.user, organization=org, defaults={"role": Membership.Role.OWNER})
    existing = Subscription.objects.select_for_update().filter(organization=org, status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIALING]).select_related("plan_version__plan").first()
    if existing:
        request.session.pop("checkout", None)
        messages.info(request, "Sua organização já possui uma assinatura ativa.")
        return render(request, "public/checkout_success.html", {"subscription": existing, "already_active": True})
    address_data = state.get("address", {})
    if address_data: Address.objects.get_or_create(organization=org, postal_code=address_data["postal_code"], defaults=address_data)
    subscription = Subscription.objects.create(organization=org, plan_version=plan, status=Subscription.Status.ACTIVE, current_period_start=timezone.now(), current_period_end=timezone.now() + timedelta(days=30))
    Payment.objects.create(subscription=subscription, amount_cents=plan.price_cents, status=Payment.Status.PAID, due_at=timezone.now(), paid_at=timezone.now(), provider_reference=f"SIM-{uuid4().hex[:10]}")
    checkout_request = CheckoutRequest.objects.create(user=request.user, plan_version=plan, installation_data={"address": address_data, "survey": state.get("survey", {})}, scheduled_for=state.get("scheduled_for") or None, status=CheckoutRequest.Status.CONFIRMED)
    checkout_request.selected_cultures.set(valid_cultures); request.session.pop("checkout", None)
    return render(request, "public/checkout_success.html", {"subscription": subscription})


def _customer_context(request):
    org = request.membership.organization
    return org, Garden.objects.filter(organization=org), Device.objects.filter(organization=org).prefetch_related("channels")


@customer_required
def customer_dashboard(request):
    org, gardens, devices = _customer_context(request); device = devices.order_by("name").first(); metrics = {}; schedule = None
    active_subscription = Subscription.objects.filter(organization=org, status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIALING]).select_related("plan_version__plan").first()
    if device:
        for channel in device.channels.filter(kind=Channel.Kind.SENSOR):
            reading = channel.readings.order_by("-recorded_at").first(); metrics[channel.metric] = {"value": reading.decimal_value if reading else None, "unit": channel.unit}
        schedule = LightingSchedule.objects.filter(actuator__device=device, enabled=True).first()
    return render(request, "customer/dashboard.html", {"organization": org, "gardens": gardens, "has_garden": gardens.exists(), "active_subscription": active_subscription, "device": device, "has_telemetry": any(item["value"] is not None for item in metrics.values()), "metrics": metrics, "schedule": schedule, "cycles": PlantingCycle.objects.filter(module__organization=org, status=PlantingCycle.Status.ACTIVE).select_related("cultivar__crop", "module")[:6], "alerts": Alert.objects.filter(rule__organization=org).select_related("rule")[:5], "next_visit": Visit.objects.filter(organization=org, scheduled_start__gte=timezone.now()).select_related("technician").order_by("scheduled_start").first()})


@customer_required
def customer_section(request, section):
    org, gardens, devices = _customer_context(request)
    sections = {"garden": ("Minha horta", gardens.prefetch_related("module_installations__module")), "crops": ("Minhas culturas", PlantingCycle.objects.filter(module__organization=org).select_related("cultivar__crop", "module")), "alerts": ("Alertas", Alert.objects.filter(rule__organization=org).select_related("rule", "reading__channel")), "visits": ("Visitas", Visit.objects.filter(organization=org).select_related("technician", "garden")), "subscription": ("Assinatura", Subscription.objects.filter(organization=org).select_related("plan_version__plan")), "payments": ("Pagamentos", Payment.objects.filter(subscription__organization=org).select_related("subscription"))}
    if section not in sections: raise Http404
    title, objects = sections[section]
    context = {"title": title, "objects": objects, "organization": org}
    if section == "crops":
        context["active_modules"] = GardenModule.objects.filter(organization=org, status=GardenModule.Status.INSTALLED).count()
        subscription = Subscription.objects.filter(organization=org, status=Subscription.Status.ACTIVE).select_related("plan_version").first()
        feature = subscription.plan_version.features.filter(key__icontains="módulo").first() if subscription else None
        context["module_limit"] = feature.limit if feature else None
    return render(request, f"customer/{section}.html", context)


@customer_required
def add_module(request):
    found = None
    if request.method == "POST":
        code = request.POST.get("code", "").strip().upper()
        found = GardenModule.objects.filter(organization=request.membership.organization, serial_number__iexact=code).first()
        if found and request.POST.get("confirm"):
            garden = Garden.objects.filter(organization=request.membership.organization, is_active=True).first()
            if not garden:
                messages.error(request, "Nenhuma horta ativa encontrada.")
            else:
                ModuleInstallation.objects.get_or_create(module=found, removed_at=None, defaults={"garden": garden, "installed_at": timezone.now()})
                found.status = GardenModule.Status.INSTALLED
                found.save(update_fields=["status", "updated_at"])
                messages.success(request, "Módulo adicionado à sua horta.")
                return redirect("customer-section", section="crops")
        elif not found:
            messages.error(request, "Código não encontrado para sua organização.")
    return render(request, "customer/add_module.html", {"found": found})


@customer_required
@require_POST
def request_crop_change(request, cycle_id):
    cycle = get_object_or_404(PlantingCycle, id=cycle_id, module__organization=request.membership.organization)
    SupportTicket.objects.create(organization=request.membership.organization, opened_by=request.user, category="Planta", subject=f"Trocar cultura — {cycle.module.serial_number}", description=f"Solicitação de substituição da cultura {cycle.cultivar.crop.common_name}.")
    messages.success(request, "Solicitação enviada para a equipe operacional.")
    return redirect("module-detail", module_id=cycle.module.id)


@customer_required
def module_detail(request, module_id):
    module = get_object_or_404(GardenModule, id=module_id, organization=request.membership.organization)
    return render(request, "customer/module_detail.html", {"module": module, "cycles": module.planting_cycles.select_related("cultivar__crop").prefetch_related("observations", "harvests")})


@customer_required
def history(request):
    org = request.membership.organization; raw_days = request.GET.get("days", "7"); days = int(raw_days) if raw_days.isdigit() and int(raw_days) in (1, 7, 30) else 7
    rows = TelemetryReading.objects.filter(channel__device__organization=org, recorded_at__gte=timezone.now() - timedelta(days=days), channel__metric__in=["air_temperature", "air_humidity", "water_level"]).annotate(bucket=TruncHour("recorded_at")).values("bucket", "channel__metric").annotate(value=Avg("decimal_value")).order_by("bucket")[:1000]
    series = {}
    for row in rows: series.setdefault(row["channel__metric"], []).append({"x": row["bucket"].isoformat(), "y": float(row["value"])})
    return render(request, "customer/history.html", {"series": series, "days": days})


@customer_required
@require_POST
def device_action(request):
    channel = get_object_or_404(Channel, id=request.POST.get("channel"), device__organization=request.membership.organization, kind=Channel.Kind.ACTUATOR); action = request.POST.get("action")
    if channel.metric == "pump_state": payload = {"on": True, "mode": "safe_preset"}
    elif action in ("on", "off"): payload = {"on": action == "on", "mode": "manual"}
    else: raise Http404
    DeviceCommand.objects.create(device=channel.device, channel=channel, command_type="set_state", payload=payload, idempotency_key=f"web:{request.user.id}:{uuid4().hex}")
    messages.success(request, "Comando enviado ao controlador."); return redirect("customer-dashboard")


@customer_required
def lighting_schedule(request, schedule_id):
    schedule = get_object_or_404(LightingSchedule, id=schedule_id, actuator__device__organization=request.membership.organization); form = LightingScheduleForm(request.POST or None, instance=schedule)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Programação atualizada."); return redirect("customer-dashboard")
    return render(request, "customer/form.html", {"title": "Editar programação", "form": form})


@customer_required
def support(request):
    form = SupportTicketForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ticket = form.save(commit=False); ticket.organization = request.membership.organization; ticket.opened_by = request.user; ticket.save(); messages.success(request, "Chamado aberto com sucesso."); return redirect("customer-support")
    return render(request, "customer/support.html", {"form": form, "tickets": SupportTicket.objects.filter(organization=request.membership.organization)})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Perfil atualizado."); return redirect("customer-profile")
    return render(request, "customer/form.html", {"title": "Meu perfil", "form": form})


@technician_required
def tech_dashboard(request):
    visits = Visit.objects.filter(technician=request.user, scheduled_start__date=timezone.localdate()).select_related("organization", "garden").order_by("scheduled_start")
    return render(request, "operations/dashboard.html", {"visits": visits, "today_count": visits.count(), "work_orders": WorkOrder.objects.filter(assignments__user=request.user).exclude(status__in=[WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELED])})


@technician_required
def tech_visits(request):
    return render(request, "operations/visits.html", {"visits": Visit.objects.filter(technician=request.user).select_related("organization", "garden").order_by("scheduled_start")})


@technician_required
def visit_detail(request, visit_id):
    visit = get_object_or_404(Visit.objects.select_related("organization", "garden", "work_order"), id=visit_id, technician=request.user)
    checklist, _ = ChecklistExecution.objects.get_or_create(visit=visit, defaults={"items": [{"label": label, "done": False} for label in ("Verificar estrutura", "Verificar bomba", "Iluminação", "Reservatório", "Sensores", "Limpeza", "Substrato", "Culturas", "Teste final")]})
    return render(request, "operations/visit_detail.html", {"visit": visit, "checklist": checklist})


@technician_required
@require_POST
def visit_update(request, visit_id):
    visit = get_object_or_404(Visit, id=visit_id, technician=request.user); checklist, _ = ChecklistExecution.objects.get_or_create(visit=visit, defaults={"items": []})
    if request.POST.get("action") == "complete":
        visit.status = Visit.Status.COMPLETED; visit.notes = request.POST.get("notes", ""); visit.save(update_fields=["status", "notes", "updated_at"])
        if visit.work_order: visit.work_order.status = WorkOrder.Status.COMPLETED; visit.work_order.completed_at = timezone.now(); visit.work_order.save(update_fields=["status", "completed_at", "updated_at"])
        messages.success(request, "Visita concluída.")
    else:
        checklist.items = [{"label": label, "done": label in request.POST.getlist("check_item")} for label in request.POST.getlist("all_item")]; checklist.save(); messages.success(request, "Checklist salvo.")
    return redirect("visit-detail", visit_id=visit.id)


@operations_required
def ops_dashboard(request):
    today = timezone.localdate()
    metrics = {"Clientes ativos": Organization.objects.filter(is_active=True).count(), "Assinaturas": Subscription.objects.filter(status=Subscription.Status.ACTIVE).count(), "Hortas instaladas": Garden.objects.filter(is_active=True).count(), "Módulos ativos": GardenModule.objects.filter(status=GardenModule.Status.INSTALLED).count(), "Dispositivos online": Device.objects.filter(status=Device.Status.ONLINE).count(), "Dispositivos offline": Device.objects.filter(status=Device.Status.OFFLINE).count(), "Visitas hoje": Visit.objects.filter(scheduled_start__date=today).count(), "Ordens abertas": WorkOrder.objects.exclude(status__in=[WorkOrder.Status.COMPLETED, WorkOrder.Status.CANCELED]).count(), "Alertas críticos": Alert.objects.filter(status=Alert.Status.OPEN, rule__severity__gte=3).count()}
    return render(request, "admin_portal/dashboard.html", {"metrics": metrics, "visits": Visit.objects.filter(scheduled_start__date=today).select_related("organization", "technician")[:8], "alerts": Alert.objects.filter(status=Alert.Status.OPEN).select_related("rule", "rule__channel__device").order_by("-rule__severity")[:8]})


@operations_required
def ops_collection(request, section):
    collections = {"clients": ("Clientes", Organization.objects.annotate(total_gardens=Count("gardens"))), "subscriptions": ("Assinaturas", Subscription.objects.select_related("organization", "plan_version__plan")), "plans": ("Planos", Plan.objects.prefetch_related("versions")), "crops": ("Culturas", Crop.objects.all()), "gardens": ("Hortas", Garden.objects.select_related("organization")), "modules": ("Módulos", GardenModule.objects.select_related("organization", "module_type")), "devices": ("Dispositivos", Device.objects.select_related("organization", "model", "module")), "telemetry": ("Telemetria", TelemetryReading.objects.select_related("channel__device")[:200]), "alerts": ("Alertas técnicos", Alert.objects.select_related("rule__channel__device")[:200]), "employees": ("Funcionários", User.objects.filter(Q(is_staff=True) | Q(memberships__role=Membership.Role.TECHNICIAN)).distinct()), "agenda": ("Agenda geral", Visit.objects.select_related("organization", "technician", "garden")), "orders": ("Ordens de serviço", WorkOrder.objects.select_related("organization", "garden", "device")), "inventory": ("Estoque", InventoryItem.objects.all()), "finance": ("Financeiro", Payment.objects.select_related("subscription__organization")), "reports": ("Relatórios", []), "settings": ("Configurações", []), "qrcodes": ("QR Codes", GardenModule.objects.all())}
    if section not in collections: raise Http404
    title, objects = collections[section]
    return render(request, "admin_portal/collection.html", {"title": title, "section": section, "objects": objects, "query": request.GET.get("q", "").strip()})


@operations_required
def create_work_order(request):
    form = WorkOrderForm(request.POST or None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Ordem criada."); return redirect("ops-collection", section="orders")
    return render(request, "admin_portal/form.html", {"title": "Criar ordem de serviço", "form": form})


def health(request): return JsonResponse({"status": "ok"})
