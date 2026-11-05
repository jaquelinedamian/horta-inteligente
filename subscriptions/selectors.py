from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from .models import Plan, PlanVersion, Subscription


def get_available_plan_versions(at=None):
    """Versão vigente mais recente de cada plano disponível para novas assinaturas."""
    at = at or timezone.now()
    latest = PlanVersion.objects.filter(
        plan=OuterRef("plan_id"), effective_from__lte=at
    ).filter(Q(retired_at__isnull=True) | Q(retired_at__gt=at)).order_by("-version", "-effective_from")
    return PlanVersion.objects.filter(
        id=Subquery(latest.values("id")[:1]), plan__is_active=True,
        price_cents__gt=0,
    ).select_related("plan", "plan__garden_model").prefetch_related("features", "entitlements").order_by("plan__display_order", "price_cents")


def get_public_plans(at=None):
    return get_available_plan_versions(at).filter(plan__is_public=True)


def get_current_plan_version(plan, at=None):
    at = at or timezone.now()
    return plan.versions.filter(effective_from__lte=at).filter(Q(retired_at__isnull=True) | Q(retired_at__gt=at)).order_by("-version", "-effective_from").first()


def get_scheduled_plan_version(plan, at=None):
    at = at or timezone.now()
    return plan.versions.filter(effective_from__gt=at).filter(Q(retired_at__isnull=True) | Q(retired_at__gt=at)).order_by("effective_from", "version").first()


def get_plan_price_state(plan, at=None):
    at = at or timezone.now()
    current = get_current_plan_version(plan, at)
    scheduled = get_scheduled_plan_version(plan, at)
    latest = plan.versions.order_by("-effective_from", "-version").first()
    if current:
        status, displayed = "current", current
    elif scheduled:
        status, displayed = "scheduled", scheduled
    elif latest:
        status, displayed = "expired", latest
    else:
        status, displayed = "missing", None
    return {"status": status, "current": current, "scheduled": scheduled, "displayed": displayed}


def plan_publication_diagnostics(plan, at=None):
    """Explain why a plan is or is not available without changing its data."""
    at = at or timezone.now()
    issues = []
    if not plan.is_active:
        issues.append("Plano inativo")
    if not plan.is_public:
        issues.append("Plano oculto no site")
    price = get_plan_price_state(plan, at)
    version = price["current"]
    if not version and price["scheduled"]:
        issues.append(f'Preço agendado para {timezone.localtime(price["scheduled"].effective_from):%d/%m/%Y %H:%M}')
    elif not version:
        issues.append("Sem versão de preço vigente")
    elif version.price_cents <= 0:
        issues.append("Preço vigente inválido")
    if not plan.garden_model_id:
        issues.append("Associe um modelo de horta")
    eligible = plan.is_active and plan.is_public and version is not None and version.price_cents > 0
    if not plan.is_active:
        publication_state = "disabled"
    elif plan.is_public and eligible:
        publication_state = "published"
    elif plan.is_public and price["scheduled"]:
        publication_state = "scheduled"
    else:
        publication_state = "draft"
    return {"version": version, "issues": issues, "is_published": eligible, "publication_state": publication_state, "price": price}


def get_customer_subscription(organization):
    return Subscription.objects.filter(
        organization=organization,
        status__in=(Subscription.Status.ACTIVE, Subscription.Status.TRIALING, Subscription.Status.PAST_DUE),
    ).select_related("plan_version__plan", "coupon").prefetch_related("plan_version__entitlements").order_by("-created_at").first()
