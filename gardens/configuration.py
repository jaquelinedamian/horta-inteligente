from copy import deepcopy
from collections.abc import Mapping

from crops.models import PlantingCycle


def safe_photos_per_day(value):
    if isinstance(value, bool):
        return 4
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return 4
    return max(1, min(value, 4))


def _merge(base, override):
    result = deepcopy(base) if isinstance(base, Mapping) else {}
    if not isinstance(override, Mapping):
        return result
    for key, value in override.items():
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
    model = garden.garden_model if garden.garden_model_id else None
    model_defaults = {"camera": {"photos_per_day": safe_photos_per_day(model.photos_per_day if model else 4)}, "monitoring": {"interval_minutes": model.monitoring_interval_minutes if model else 60}}
    if model and model.light_hours_per_day is not None:
        model_defaults["lighting"] = {"hours_per_day": float(model.light_hours_per_day)}
    if model and (model.irrigation_frequency_count is not None or model.pump_duration_seconds is not None):
        model_defaults["irrigation"] = {"frequency_count": model.irrigation_frequency_count, "frequency_period": model.irrigation_frequency_period, "pump_duration_seconds": model.pump_duration_seconds}
    config = _merge(model_defaults, candidates[0] if compatible else {})
    config = _merge(config, garden.automation_overrides)
    config["cultures"] = [(cycle.crop or cycle.cultivar.crop).code for cycle in cycles if cycle.crop_id or cycle.cultivar_id]
    config["culture"] = config["cultures"][0] if len(config["cultures"]) == 1 else None
    config["requires_confirmation"] = bool(candidates and not compatible)
    config["camera"] = _merge(
        {"photos_per_day": safe_photos_per_day(model.photos_per_day if model else 4)},
        config.get("camera") if isinstance(config.get("camera"), Mapping) else {},
    )
    config["camera"]["photos_per_day"] = safe_photos_per_day(config["camera"].get("photos_per_day"))
    config["configuration_version"] = garden.updated_at.isoformat()
    return config
