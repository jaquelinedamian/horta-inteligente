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
    {"icon": "bi-laptop", "title": "Acesso à plataforma"},
    {"icon": "bi-bar-chart-line", "title": "Relatórios e históricos"},
    {"icon": "bi-sun", "title": "Programação de iluminação"},
    {"icon": "bi-droplet", "title": "Programação de irrigação"},
    {"icon": "bi-headset", "title": "Suporte técnico"},
)


def model_specifications(model, *, include_missing=False):
    if not model:
        values = (("bi-flower1", "Quantidade de plantas", None, "plantas"),
                  ("bi-droplet", "Capacidade do reservatório", None, "L"),
                  ("bi-rulers", "Dimensões externas", None, "cm"))
    else:
        dimensions = None
        if all(value is not None for value in (model.height_cm, model.width_cm, model.depth_cm)):
            dimensions = " × ".join(format(value, "f").rstrip("0").rstrip(".") for value in (model.height_cm, model.width_cm, model.depth_cm))
        values = (("bi-flower1", "Quantidade de plantas", model.capacity, "plantas"),
                  ("bi-droplet", "Capacidade do reservatório", model.reservoir_liters, "L"),
                  ("bi-rulers", "Dimensões externas", dimensions, "cm"))
    return [{"icon": icon, "name": name, "value": value, "unit": unit}
            for icon, name, value, unit in values if include_missing or value not in (None, "")]


def shared_plan_context(model=None, *, include_missing=False):
    return {"standard_plan_features": PLAN_FEATURES, "standard_plan_services": PLAN_SERVICES,
            "model_specifications": model_specifications(model, include_missing=include_missing)}
