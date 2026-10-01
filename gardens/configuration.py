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
    cycles = list(
        PlantingCycle.objects.filter(garden=garden, status=PlantingCycle.Status.ACTIVE)
        .select_related("crop", "cultivar__crop", "cultivation_profile")
        .order_by("module__position_label", "created_at")
    )
    candidates = []
    for cycle in cycles:
        crop = cycle.crop or (cycle.cultivar.crop if cycle.cultivar_id else None)
        candidate = deepcopy(cycle.cultivation_profile.automation_config) if cycle.cultivation_profile else {}
        if crop:
            simple = {}
            if crop.light_hours is not None:
                simple["lighting"] = {"hours_per_day": float(crop.light_hours)}
            irrigation = {}
            if crop.irrigation_frequency_count is not None:
                irrigation.update(frequency_count=crop.irrigation_frequency_count, frequency_period=crop.irrigation_frequency_period)
            if crop.pump_duration_seconds is not None:
                irrigation["pump_duration_seconds"] = crop.pump_duration_seconds
            if irrigation:
                simple["irrigation"] = irrigation
            candidate = _merge(candidate, simple)
        candidates.append(candidate)
    compatible = bool(candidates) and all(item == candidates[0] for item in candidates[1:])
    config = _merge(candidates[0] if compatible else {}, garden.automation_overrides)
    config["cultures"] = [(cycle.crop or cycle.cultivar.crop).code for cycle in cycles if cycle.crop_id or cycle.cultivar_id]
    config["culture"] = config["cultures"][0] if len(config["cultures"]) == 1 else None
    config["requires_confirmation"] = bool(candidates and not compatible)
    config["camera"] = _merge(
        {"photos_per_day": garden.garden_model.photos_per_day if garden.garden_model_id else None},
        config.get("camera", {}),
    )
    config["configuration_version"] = garden.updated_at.isoformat()
    return config
