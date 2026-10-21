from copy import deepcopy
from collections.abc import Mapping

from crops.models import PlantingCycle


def lighting_duration_seconds(start_time, end_time):
    start = start_time.hour * 3600 + start_time.minute * 60 + start_time.second
    end = end_time.hour * 3600 + end_time.minute * 60 + end_time.second
    return (end - start) % 86400 or 86400


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
    from devices.models import Device
    from devices.selectors import devices_for_garden

    controller = devices_for_garden(garden).filter(kind=Device.Kind.CONTROLLER).prefetch_related(
        "channels__irrigation_schedules", "channels__lighting_schedules"
    ).first()
    if controller:
        soil = controller.channels.filter(metric="soil_moisture", is_enabled=True).first()
        if soil:
            config["soil_moisture"] = {
                "dry_raw": int(soil.configuration.get("dry_raw", 850)),
                "wet_raw": int(soil.configuration.get("wet_raw", 350)),
            }
        pump = controller.channels.filter(metric="pump_state", is_enabled=True).first()
        if pump:
            schedules = [
                {
                    "id": str(item.id), "time": item.start_time.strftime("%H:%M"),
                    "duration_seconds": item.duration_seconds, "days": item.days_of_week,
                    "enabled": item.enabled,
                }
                for item in pump.irrigation_schedules.all().order_by("start_time")
            ]
            if schedules or "irrigation" in config:
                irrigation = config.setdefault("irrigation", {})
                irrigation["schedules"] = schedules
                irrigation["enabled"] = any(item["enabled"] for item in schedules) if schedules else irrigation.get("enabled", False)
                if schedules:
                    irrigation["times"] = [item["time"] for item in schedules if item["enabled"]]
                    active = [item for item in schedules if item["enabled"]]
                    if active:
                        irrigation["duration_seconds"] = active[0]["duration_seconds"]
        light = controller.channels.filter(metric="light_state", is_enabled=True).first()
        if light:
            schedules = [
                {
                    "id": str(item.id), "start": item.start_time.strftime("%H:%M"),
                    "end": item.end_time.strftime("%H:%M"), "days": item.days_of_week,
                    "enabled": item.enabled,
                    "duration_seconds": lighting_duration_seconds(item.start_time, item.end_time),
                }
                for item in light.lighting_schedules.all().order_by("start_time")
            ]
            if schedules or "lighting" in config:
                lighting = config.setdefault("lighting", {})
                lighting["schedules"] = schedules
                lighting["enabled"] = any(item["enabled"] for item in schedules)
                active = [item for item in schedules if item["enabled"]]
                lighting["times"] = [item["start"] for item in active]
                if active:
                    lighting["duration_seconds"] = active[0]["duration_seconds"]
                    lighting["duration_hours"] = active[0]["duration_seconds"] / 3600
    config["configuration_version"] = garden.updated_at.isoformat()
    return config
