from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from crops.models import PlantingCycle
from subscriptions.models import CheckoutRequest
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
    cycles = PlantingCycle.objects.filter(
        garden=garden, status=PlantingCycle.Status.ACTIVE
    ).select_related("crop", "cultivar__crop", "cultivation_profile", "nutrition_plan")
    cycle = cycles.first()
    checkout = None
    if garden.subscription_id:
        checkout = CheckoutRequest.objects.filter(
            user__memberships__organization=garden.organization,
            plan_version=garden.subscription.plan_version,
            status=CheckoutRequest.Status.CONFIRMED,
        ).prefetch_related("selected_crops").order_by("-created_at").first()
    actuator_channels = [channel for device in devices for channel in device.channels.all() if channel.kind == "actuator" and channel.is_enabled]
    return {
        "garden": garden,
        "devices": devices,
        "metrics": metrics,
        "cycle": cycle,
        "cycles": cycles,
        "contracted_crops": checkout.selected_crops.all() if checkout else [],
        "controller": next((item for item in devices if item.kind == Device.Kind.CONTROLLER), None),
        "camera": next((item for item in devices if item.kind == Device.Kind.CAMERA), None),
        "pump_channel": next((item for item in actuator_channels if item.metric == "pump_state"), None),
        "light_channel": next((item for item in actuator_channels if item.metric == "light_state"), None),
        "next_visit": garden.visits.filter(scheduled_start__gte=timezone.now(), status="scheduled").order_by("scheduled_start").first(),
        "latest_photo": GardenPhoto.objects.filter(garden=garden).first(),
        "alerts": Alert.objects.filter(rule__channel__device__in=devices).select_related("rule")[:5],
        **garden_status(garden),
    }
