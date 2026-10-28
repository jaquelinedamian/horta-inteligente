from datetime import timedelta

from django.db import transaction
from django.db.models import Avg, Count, Max, Min
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone

from accounts.models import User
from devices.models import AlertRule, Device, DeviceCommand, GardenPhoto, TelemetryReading
from gardens.configuration import effective_garden_configuration
from gardens.models import GardenConfigurationEvent


OPERATIONAL_KEYS = ("irrigation", "lighting", "camera", "monitoring")


def configuration_origin(user, restore=False):
    if restore:
        return GardenConfigurationEvent.Origin.RESTORE
    if user.is_hortaviva_admin:
        return GardenConfigurationEvent.Origin.ADMIN
    if user.employee_role == User.EmployeeRole.TECHNICIAN:
        return GardenConfigurationEvent.Origin.TECHNICIAN
    return GardenConfigurationEvent.Origin.CUSTOMER


@transaction.atomic
def update_garden_configuration(*, garden, user, cleaned_data):
    previous = effective_garden_configuration(garden)
    overrides = garden.automation_overrides if isinstance(garden.automation_overrides, dict) else {}
    garden.automation_overrides = {
        **overrides,
        "lighting": {"hours_per_day": float(cleaned_data["light_hours"])},
        "irrigation": {
            "frequency_count": cleaned_data["irrigation_frequency_count"],
            "frequency_period": cleaned_data["irrigation_frequency_period"],
            "pump_duration_seconds": cleaned_data["pump_duration_seconds"],
        },
        "camera": {"photos_per_day": cleaned_data["photos_per_day"]},
        "monitoring": {"interval_minutes": cleaned_data["monitoring_interval_minutes"]},
    }
    garden.save(update_fields=["automation_overrides", "updated_at"])
    current = effective_garden_configuration(garden)
    GardenConfigurationEvent.objects.create(garden=garden, user=user, origin=configuration_origin(user), previous_configuration=previous, new_configuration=current)
    return current


@transaction.atomic
def restore_garden_configuration(*, garden, user):
    previous = effective_garden_configuration(garden)
    overrides = garden.automation_overrides if isinstance(garden.automation_overrides, dict) else {}
    garden.automation_overrides = {key: value for key, value in overrides.items() if key not in OPERATIONAL_KEYS}
    garden.save(update_fields=["automation_overrides", "updated_at"])
    current = effective_garden_configuration(garden)
    GardenConfigurationEvent.objects.create(garden=garden, user=user, origin=configuration_origin(user, True), previous_configuration=previous, new_configuration=current)
    return current


SENSOR_META = {
    "air_temperature": {"label": "Temperatura", "unit": "°C", "profile": ("target_temperature_min", "target_temperature_max")},
    "soil_moisture": {"label": "Umidade do solo", "unit": "%", "profile": ("substrate_moisture_min", "substrate_moisture_max")},
    "air_pressure": {"label": "Pressão atmosférica", "unit": "hPa", "profile": (None, None)},
}


def _report_window(period, start=None, end=None):
    now = timezone.now()
    if period == "custom" and start and end:
        return start, end, "hour" if end - start <= timedelta(days=7) else "day"
    if period == "today":
        return timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0), now, "hour"
    days = {"24h": 1, "7d": 7, "30d": 30}.get(period, 7)
    return now - timedelta(days=days), now, "day" if days == 30 else "hour"


def _sensor_limits(garden, metric):
    low_field, high_field = SENSOR_META[metric]["profile"]
    if low_field:
        cycle = garden.planting_cycles.filter(status="active", cultivation_profile__isnull=False).select_related("cultivation_profile").first()
        if cycle:
            low = getattr(cycle.cultivation_profile, low_field)
            high = getattr(cycle.cultivation_profile, high_field)
            if low is not None or high is not None:
                return {"minimum": low, "maximum": high, "source": "Perfil de cultivo"}
    return None


def _rule_matches(value, operator, threshold):
    return {"lt": value < threshold, "lte": value <= threshold, "gt": value > threshold,
            "gte": value >= threshold, "eq": value == threshold}.get(operator, False)


def _classification(garden, metric, value, limits):
    if value is None or not limits:
        profile_state = None
    else:
        low, high = limits["minimum"], limits["maximum"]
        outside = (low is not None and value < low) or (high is not None and value > high)
        profile_state = "attention" if outside else "ideal"
    rules = AlertRule.objects.filter(
        organization=garden.organization, channel__device__garden=garden,
        channel__metric=metric, is_active=True,
    ).only("operator", "threshold", "severity")
    matched = [rule for rule in rules if _rule_matches(value, rule.operator, rule.threshold)] if value is not None else []
    if matched:
        return "critical" if max(rule.severity for rule in matched) >= 3 else "attention"
    return profile_state


def garden_report(garden, period, start=None, end=None):
    since, until, aggregation = _report_window(period, start, end)
    readings = TelemetryReading.objects.filter(
        channel__device__garden=garden, recorded_at__gte=since, recorded_at__lte=until,
    )
    trunc = TruncDay("recorded_at") if aggregation == "day" else TruncHour("recorded_at")
    sensor_data = {}
    for metric, meta in SENSOR_META.items():
        qs = readings.filter(channel__metric=metric)
        stats = qs.aggregate(average=Avg("decimal_value"), minimum=Min("decimal_value"), maximum=Max("decimal_value"))
        points = list(qs.annotate(bucket=trunc).values("bucket").annotate(value=Avg("decimal_value")).order_by("bucket"))
        latest = list(qs.order_by("-recorded_at").values("decimal_value", "recorded_at")[:2])
        current = latest[0]["decimal_value"] if latest else None
        previous = latest[1]["decimal_value"] if len(latest) > 1 else None
        limits = _sensor_limits(garden, metric)
        sensor_data[metric] = {
            **stats, "points": points, "configured": qs.exists() or garden.devices.filter(channels__metric=metric).exists(),
            "label": meta["label"], "unit": meta["unit"], "current": current,
            "recorded_at": latest[0]["recorded_at"] if latest else None,
            "delta": current - previous if current is not None and previous is not None else None,
            "limits": limits, "classification": _classification(garden, metric, current, limits),
        }
    command_queryset = DeviceCommand.objects.filter(
        channel__device__garden=garden, channel__metric="pump_state", created_at__gte=since,
        created_at__lte=until,
    )
    commands = list(command_queryset.filter(status=DeviceCommand.Status.SUCCEEDED).order_by("-created_at"))
    all_commands = list(command_queryset.only("payload"))
    durations = [int((command.payload or {}).get("duration_seconds") or 0) for command in all_commands]
    photos = GardenPhoto.objects.filter(garden=garden, captured_at__gte=since, captured_at__lte=until)
    config = effective_garden_configuration(garden)
    interval = max(1, int(config.get("monitoring", {}).get("interval_minutes") or 60))
    newest = max((item["recorded_at"] for item in sensor_data.values() if item["recorded_at"]), default=None)
    stale = newest is None or timezone.now() - newest > timedelta(minutes=interval * 2)
    controller = Device.objects.filter(garden=garden, kind=Device.Kind.CONTROLLER).order_by("created_at").first()
    device_offline = bool(controller and not controller.is_online)
    events = list(DeviceCommand.objects.filter(
        channel__device__garden=garden, channel__metric__in=("pump_state", "light_state"),
        status=DeviceCommand.Status.SUCCEEDED, acknowledged_at__gte=since, acknowledged_at__lte=until,
    ).select_related("channel").order_by("acknowledged_at"))
    return {
        "period": period, "start": since, "end": until, "aggregation": aggregation,
        "sensors": sensor_data, "last_measurement_at": newest, "is_stale": stale,
        "device_offline": device_offline, "monitoring_interval": interval,
        "events": events, "irrigation_commands": commands,
        "irrigation_count": len(all_commands), "irrigation_total": sum(durations),
        "irrigation_average": sum(durations) / len(durations) if durations else 0,
        "photo_count": photos.count(), "last_photo": photos.first(),
        "photos_by_day": list(photos.annotate(day=TruncDay("captured_at")).values("day").annotate(count=Count("id")).order_by("day")),
        "configuration": config,
        "configuration_events": garden.configuration_events.select_related("user")[:20],
    }
