from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from crops.models import PlantingCycle
from .models import Alert, Device, GardenPhoto


def devices_for_garden(garden):
    return Device.objects.filter(
        Q(garden=garden)
        | Q(module__installations__garden=garden, module__installations__removed_at__isnull=True)
    ).select_related("model", "garden").prefetch_related("channels").distinct()


def garden_status(garden):
    devices = devices_for_garden(garden)
    last_seen = max((d.last_seen_at for d in devices if d.last_seen_at), default=None)
    threshold = timedelta(seconds=getattr(settings, "DEVICE_ONLINE_THRESHOLD_SECONDS", 300))
    return {
        "online": bool(last_seen and last_seen >= timezone.now() - threshold),
        "last_seen": last_seen,
    }


def garden_snapshot(garden):
    devices = list(devices_for_garden(garden))
    metrics = {}
    for device in devices:
        for channel in device.channels.filter(kind="sensor", is_enabled=True):
            reading = channel.readings.order_by("-recorded_at").first()
            current = metrics.get(channel.metric)
            if reading and (not current or reading.recorded_at > current["recorded_at"]):
                value = reading.decimal_value
                if value is None and reading.boolean_value is not None:
                    value = reading.boolean_value
                metrics[channel.metric] = {
                    "value": value, "unit": channel.unit, "recorded_at": reading.recorded_at,
                }
    cycle = PlantingCycle.objects.filter(
        garden=garden, status=PlantingCycle.Status.ACTIVE
    ).select_related("crop", "cultivar", "cultivation_profile", "nutrition_plan").first()
    return {
        "garden": garden,
        "devices": devices,
        "metrics": metrics,
        "cycle": cycle,
        "latest_photo": GardenPhoto.objects.filter(garden=garden).first(),
        "alerts": Alert.objects.filter(rule__channel__device__in=devices).select_related("rule")[:5],
        **garden_status(garden),
    }
