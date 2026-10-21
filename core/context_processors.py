from accounts.models import Membership

from .backoffice import BACKOFFICE_AREAS, SECTION_AREA


def navigation_mode(request):
    """Select the portal navigation from identity, never from a shared URL."""
    user = request.user
    if not user.is_authenticated:
        return {"navigation_mode": None}
    if user.is_hortaviva_admin:
        mode = "admin"
    elif user.employee_role == user.EmployeeRole.TECHNICIAN or user.memberships.filter(
        is_active=True, role=Membership.Role.TECHNICIAN
    ).exists():
        mode = "technician"
    else:
        mode = "customer"
    return {"navigation_mode": mode}


def backoffice_navigation(request):
    if not request.path.startswith("/gestao/"):
        return {}
    match = getattr(request, "resolver_match", None)
    section = match.kwargs.get("section") if match else None
    area = match.kwargs.get("area") if match else None
    if not area and section:
        area = SECTION_AREA.get(section)
    if not area:
        area = "administracao"
    return {
        "backoffice_areas": BACKOFFICE_AREAS,
        "backoffice_current_area": area,
        "backoffice_current_section": section,
        "backoffice_area_config": BACKOFFICE_AREAS[area],
    }
