"""Shared commercial presentation for every HortaViva plan."""

PLAN_FEATURES = (
    {"icon": "bi-droplet", "title": "Irrigação automatizada"},
    {"icon": "bi-sun", "title": "Iluminação LED grow"},
    {"icon": "bi-bar-chart-line", "title": "Monitoramento online"},
    {"icon": "bi-camera-video", "title": "Câmera Wi-Fi"},
    {"icon": "bi-headset", "title": "Suporte técnico"},
    {"icon": "bi-laptop", "title": "Acesso à plataforma"},
)

PLAN_SERVICES = (
    {"icon": "bi-laptop", "title": "Acesso à plataforma", "benefit_types": ("platform-access",)},
    {"icon": "bi-bar-chart-line", "title": "Relatórios e históricos", "benefit_types": ("reports-history", "reports")},
    {"icon": "bi-sun", "title": "Programação de iluminação", "benefit_types": ("programmable-lighting", "lighting-schedule")},
    {"icon": "bi-droplet", "title": "Programação de irrigação", "benefit_types": ("automatic-irrigation", "irrigation-schedule")},
    {"icon": "bi-headset", "title": "Suporte técnico", "benefit_types": ("technical-support",)},
)


def _compact_measurement(value):
    if value in (None, ""):
        return value
    return format(value, "f").rstrip("0").rstrip(".")


def model_specifications(model, *, include_missing=False, separate_dimensions=False):
    if not model:
        dimensions = (("bi-arrows-vertical", "Altura", None, "cm"),
                      ("bi-arrows", "Largura", None, "cm"),
                      ("bi-box", "Profundidade", None, "cm")) if separate_dimensions else (
                          ("bi-rulers", "Dimensões externas", None, "cm"),)
        values = (("bi-flower1", "Quantidade de plantas", None, "plantas"),
                  ("bi-droplet", "Capacidade do reservatório", None, "L"), *dimensions)
    else:
        if separate_dimensions:
            dimensions = (("bi-arrows-vertical", "Altura", _compact_measurement(model.height_cm), "cm"),
                          ("bi-arrows", "Largura", _compact_measurement(model.width_cm), "cm"),
                          ("bi-box", "Profundidade", _compact_measurement(model.depth_cm), "cm"))
        else:
            dimension_values = (model.height_cm, model.width_cm, model.depth_cm)
            combined = " × ".join(_compact_measurement(value) for value in dimension_values) if all(
                value is not None for value in dimension_values) else None
            dimensions = (("bi-rulers", "Dimensões externas", combined, "cm"),)
        values = (("bi-flower1", "Quantidade de plantas", model.capacity, "plantas"),
                  ("bi-droplet", "Capacidade do reservatório", model.reservoir_liters, "L"),
                  *dimensions)
    return [{"icon": icon, "name": name, "value": value, "unit": unit}
            for icon, name, value, unit in values if include_missing or value not in (None, "")]


def plan_services(version=None):
    services = [{"icon": item["icon"], "title": item["title"], "description": ""} for item in PLAN_SERVICES]
    if not version:
        return services

    entitlements = sorted(
        (item for item in version.entitlements.all() if item.is_included and item.description.strip()),
        key=lambda item: (item.display_order, item.created_at),
    )
    for service, definition in zip(services, PLAN_SERVICES):
        matching = next((item for item in entitlements if
                         item.benefit_type in definition["benefit_types"] or
                         item.name.strip().casefold() == definition["title"].casefold()), None)
        if matching:
            service["description"] = matching.description.strip()
    return services


def shared_plan_context(model=None, *, version=None, include_missing=False, separate_dimensions=False):
    return {"standard_plan_features": PLAN_FEATURES, "standard_plan_services": plan_services(version),
            "model_specifications": model_specifications(
                model, include_missing=include_missing, separate_dimensions=separate_dimensions)}
