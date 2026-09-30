from django.db.models import Q

from accounts.models import Membership
from .models import Garden


CUSTOMER_ROLES = (Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.VIEWER)


def gardens_for_user(user):
    """Escopo único: cliente próprio, técnico atribuído, admin global."""
    if not user.is_authenticated:
        return Garden.objects.none()
    if user.is_staff or user.is_superuser:
        return Garden.objects.all()

    customer_orgs = user.memberships.filter(
        is_active=True, role__in=CUSTOMER_ROLES
    ).values("organization_id")
    is_technician = user.memberships.filter(
        is_active=True, role=Membership.Role.TECHNICIAN
    ).exists()
    scope = Q(organization_id__in=customer_orgs) | Q(members__user=user)
    if is_technician:
        scope |= (
            Q(primary_technician=user)
            | Q(visits__technician=user)
            | Q(work_orders__assignments__user=user)
        )
    return Garden.objects.filter(scope).distinct()


def user_can_access_garden(user, garden):
    return gardens_for_user(user).filter(pk=garden.pk).exists()
