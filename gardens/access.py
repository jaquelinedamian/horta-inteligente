from django.db.models import Q

from accounts.models import Membership
from .models import Garden


CUSTOMER_ROLES = (Membership.Role.OWNER, Membership.Role.MANAGER, Membership.Role.VIEWER)


def gardens_for_user(user):
    """Escopo único: cliente próprio, técnico atribuído, admin global."""
    if not user.is_authenticated:
        return Garden.objects.none()
    if user.is_hortaviva_admin:
        return Garden.objects.all()

    is_technician = user.employee_role == user.EmployeeRole.TECHNICIAN or user.memberships.filter(
        is_active=True, role=Membership.Role.TECHNICIAN
    ).exists()
    if is_technician:
        return Garden.objects.filter(
            Q(members__user=user)
            | Q(primary_technician=user)
            | Q(visits__technician=user)
            | Q(work_orders__assignments__user=user)
        ).distinct()

    customer_orgs = user.memberships.filter(
        is_active=True, role__in=CUSTOMER_ROLES
    ).values("organization_id")
    return Garden.objects.filter(Q(organization_id__in=customer_orgs) | Q(members__user=user)).distinct()


def user_can_access_garden(user, garden):
    return gardens_for_user(user).filter(pk=garden.pk).exists()
