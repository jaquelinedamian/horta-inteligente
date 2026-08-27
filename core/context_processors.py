from .backoffice import BACKOFFICE_AREAS, SECTION_AREA


def backoffice_navigation(request):
    if not request.path.startswith("/gestao/"):
        return {}
    match = getattr(request, "resolver_match", None)
    section = match.kwargs.get("section") if match else None
    area = match.kwargs.get("area") if match else None
    if not area and section:
        area = SECTION_AREA.get(section)
    if not area:
        area = "comercial"
    return {
        "backoffice_areas": BACKOFFICE_AREAS,
        "backoffice_current_area": area,
        "backoffice_current_section": section,
        "backoffice_area_config": BACKOFFICE_AREAS[area],
    }
