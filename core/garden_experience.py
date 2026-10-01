from datetime import timedelta

from django.db import transaction
from django.db.models import Avg, Count, Max, Min
from django.db.models.functions import TruncDay, TruncHour
from django.utils import timezone

from accounts.models import User
from devices.models import DeviceCommand, GardenPhoto, TelemetryReading
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


def garden_report(garden, period):
    days = {"today": 1, "24h": 1, "7d": 7, "30d": 30}.get(period, 7)
    since = timezone.now() - timedelta(days=days)
    readings = TelemetryReading.objects.filter(channel__device__garden=garden, recorded_at__gte=since)
    trunc = TruncDay("recorded_at") if days == 30 else TruncHour("recorded_at")
    sensor_data = {}
    for metric in ("air_temperature", "air_humidity"):
        qs = readings.filter(channel__metric=metric)
        stats = qs.aggregate(average=Avg("decimal_value"), minimum=Min("decimal_value"), maximum=Max("decimal_value"))
        points = list(qs.annotate(bucket=trunc).values("bucket").annotate(value=Avg("decimal_value")).order_by("bucket"))
        sensor_data[metric] = {**stats, "points": points, "configured": qs.exists() or garden.devices.filter(channels__metric=metric).exists()}
    commands = list(DeviceCommand.objects.filter(channel__device__garden=garden, channel__metric="pump_state", created_at__gte=since).order_by("-created_at"))
    durations = [int((command.payload or {}).get("duration_seconds") or 0) for command in commands]
    photos = GardenPhoto.objects.filter(garden=garden, captured_at__gte=since)
    config = effective_garden_configuration(garden)
    return {
        "period": period, "sensors": sensor_data, "irrigation_commands": commands,
        "irrigation_count": len(commands), "irrigation_total": sum(durations),
        "irrigation_average": sum(durations) / len(durations) if durations else 0,
        "photo_count": photos.count(), "last_photo": photos.first(),
        "photos_by_day": list(photos.annotate(day=TruncDay("captured_at")).values("day").annotate(count=Count("id")).order_by("day")),
        "configuration": config,
        "configuration_events": garden.configuration_events.select_related("user")[:20],
    }
