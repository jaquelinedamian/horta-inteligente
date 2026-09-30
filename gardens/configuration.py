from copy import deepcopy

from crops.models import PlantingCycle


def _merge(base, override):
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def effective_garden_configuration(garden):
    cycle = (
        PlantingCycle.objects.filter(garden=garden, status=PlantingCycle.Status.ACTIVE)
        .select_related("crop", "cultivation_profile", "nutrition_plan")
        .order_by("-planted_at", "-created_at")
        .first()
    )
    defaults = cycle.cultivation_profile.automation_config if cycle and cycle.cultivation_profile else {}
    config = _merge(defaults, garden.automation_overrides)
    config["culture"] = cycle.crop.code if cycle and cycle.crop else None
    config["configuration_version"] = garden.updated_at.isoformat()
    return config
