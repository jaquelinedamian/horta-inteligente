from django.db.models import OuterRef, Subquery

from .models import PlanVersion, Subscription


def get_available_plan_versions(at=None):
    """Latest commercial version for each active plan; dates are historical only."""
    latest = PlanVersion.objects.filter(plan=OuterRef("plan_id")).order_by("-version", "-created_at")
    return PlanVersion.objects.filter(
        id=Subquery(latest.values("id")[:1]), plan__is_active=True, price_cents__gt=0,
    ).select_related("plan", "plan__garden_model").prefetch_related("features", "entitlements", "plan__garden_model__physical_features").order_by("plan__display_order", "price_cents")


def get_public_plans(at=None):
    return get_available_plan_versions(at).filter(plan__is_public=True)


def get_current_plan_version(plan, at=None):
    return plan.versions.order_by("-version", "-created_at").first()


def get_plan_price_state(plan, at=None):
    version = get_current_plan_version(plan)
    return {"status": "current" if version else "missing", "current": version, "scheduled": None, "displayed": version}


def plan_publication_diagnostics(plan, at=None):
    version = get_current_plan_version(plan)
    issues = []
    if not plan.is_active:
        issues.append("Plano desativado")
    if not plan.is_public:
        issues.append("Plano despublicado")
    if not version:
        issues.append("Preço não cadastrado")
    elif version.price_cents <= 0:
        issues.append("Preço inválido")
    blocking_issues = []
    if not plan.name:
        blocking_issues.append("nome do plano")
    if not version or version.price_cents <= 0:
        blocking_issues.append("mensalidade válida")
    issues.extend(f"Cadastro incompleto: {issue}" for issue in blocking_issues)
    published = bool(plan.is_active and plan.is_public and version and version.price_cents > 0)
    state = "incomplete" if blocking_issues else ("published" if published else ("unpublished" if plan.is_active and not plan.is_public else "draft"))
    return {"version": version, "issues": issues, "blocking_issues": blocking_issues, "can_publish": not blocking_issues, "is_published": published, "publication_state": state, "price": get_plan_price_state(plan)}


def get_customer_subscription(organization):
    return Subscription.objects.filter(
        organization=organization,
        status__in=(Subscription.Status.ACTIVE, Subscription.Status.TRIALING, Subscription.Status.PAST_DUE),
    ).select_related("plan_version__plan", "plan_version__plan__garden_model", "coupon").prefetch_related("plan_version__entitlements").order_by("-created_at").first()
