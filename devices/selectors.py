from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from crops.models import PlantingCycle
from gardens.configuration import effective_garden_configuration
from subscriptions.models import CheckoutRequest
from .models import Alert, Device, DeviceCommand, GardenPhoto


def _command_state(command, metric):
    if not command:
        return False
    result = command.result if isinstance(command.result, dict) else {}
    key = "pump" if metric == "pump_state" else "lamp"
    return bool(result.get("relay", result.get(key, command.payload.get("on", False))))


def _command_origin(command):
    if not command:
        return None
    source = command.payload.get("source", "")
    automatic = source.endswith("schedule") or command.idempotency_key.startswith(("lighting:", "irrigation:"))
    return "Automática" if automatic else "Manual"


def _next_lighting_action(schedules, now):
    candidates = []
    for schedule in schedules:
        zone = ZoneInfo(schedule.timezone)
        local_now = now.astimezone(zone)
        for offset in range(8):
            day = local_now.date() + timedelta(days=offset)
            if day.weekday() not in schedule.days_of_week:
                continue
            start = timezone.make_aware(datetime.combine(day, schedule.start_time), zone)
            end_day = day if schedule.end_time > schedule.start_time else day + timedelta(days=1)
            end = timezone.make_aware(datetime.combine(end_day, schedule.end_time), zone)
            if start > now:
                candidates.append((start, "Ligar"))
            if end > now:
                candidates.append((end, "Desligar"))
            if start > now and end > now:
                break
    return min(candidates, key=lambda item: item[0]) if candidates else None


def _confirmed_actuator_state(channel, controller, diagnostic_keys, freshness_minutes):
    """Retorna somente estado informado pelo dispositivo, nunca o solicitado."""
    candidates = []
    reading = channel.readings.filter(boolean_value__isnull=False).order_by("-recorded_at").first() if channel else None
    if reading:
        candidates.append((reading.recorded_at, bool(reading.boolean_value), "telemetry"))
    heartbeat = controller.latest_heartbeat if controller else None
    diagnostics = heartbeat.diagnostics if heartbeat and isinstance(heartbeat.diagnostics, dict) else {}
    for diagnostic_key in diagnostic_keys:
        if diagnostic_key in diagnostics:
            candidates.append((heartbeat.recorded_at, bool(diagnostics[diagnostic_key]), "heartbeat"))
            break
    if not candidates:
        return {"state": None, "last_state": None, "confirmed_at": None, "source": None, "is_recent": False}
    confirmed_at, state, source = max(candidates, key=lambda item: item[0])
    is_recent = bool(controller and controller.is_online and timezone.now() - confirmed_at <= timedelta(minutes=freshness_minutes))
    return {"state": state if is_recent else None, "last_state": state, "confirmed_at": confirmed_at, "source": source, "is_recent": is_recent}


def _command_feedback(channel, confirmed_at):
    """Estado transitório do comando, sem convertê-lo em estado físico."""
    if not channel:
        return {"updating": False, "confirmation_failed": False, "command": None}
    latest = channel.commands.order_by("-created_at").first()
    if not latest or (confirmed_at and latest.created_at <= confirmed_at):
        return {"updating": False, "confirmation_failed": False, "command": latest}
    return {
        "updating": latest.status in {DeviceCommand.Status.PENDING, DeviceCommand.Status.DELIVERED},
        "confirmation_failed": latest.status in {DeviceCommand.Status.FAILED, DeviceCommand.Status.EXPIRED},
        "command": latest,
    }


def actuator_automation_summary(snapshot):
    """Resumo factual dos atuadores; não infere eventos offline não reportados."""
    now = timezone.now()
    controller = snapshot.get("controller")
    pump = snapshot.get("pump_channel")
    light = snapshot.get("light_channel")
    pump_schedules = list(pump.irrigation_schedules.filter(enabled=True).order_by("start_time")) if pump else []
    light_schedules = list(light.lighting_schedules.filter(enabled=True).order_by("start_time")) if light else []
    last_pump_on = pump.commands.filter(status=DeviceCommand.Status.SUCCEEDED, payload__on=True).order_by("-acknowledged_at").first() if pump else None
    last_light_on = light.commands.filter(status=DeviceCommand.Status.SUCCEEDED, payload__on=True).order_by("-acknowledged_at").first() if light else None
    last_light_off = light.commands.filter(status=DeviceCommand.Status.SUCCEEDED, payload__on=False).order_by("-acknowledged_at").first() if light else None
    config = effective_garden_configuration(snapshot["garden"])
    freshness_minutes = max(2, int((config.get("monitoring") or {}).get("interval_minutes") or 60) * 2)
    pump_confirmation = _confirmed_actuator_state(
        pump, controller, ("pump_on", "relay_pump_on", "relay_on"), freshness_minutes
    )
    light_confirmation = _confirmed_actuator_state(
        light, controller, ("lamp_on", "relay_light_on"), freshness_minutes
    )
    pump_feedback = _command_feedback(pump, pump_confirmation["confirmed_at"])
    light_feedback = _command_feedback(light, light_confirmation["confirmed_at"])
    pump_state = pump_confirmation["state"] is True
    light_state = light_confirmation["state"] is True
    pump_duration = last_pump_on.payload.get("duration_seconds") if last_pump_on else None
    pump_end = last_pump_on.acknowledged_at + timedelta(seconds=pump_duration) if pump_state and last_pump_on and last_pump_on.acknowledged_at and pump_duration else None
    if pump_end and pump_end <= now:
        pump_end = None
    light_cycle = None
    if last_light_off and last_light_off.acknowledged_at:
        cycle_start = light.commands.filter(
            status=DeviceCommand.Status.SUCCEEDED, payload__on=True,
            acknowledged_at__lt=last_light_off.acknowledged_at,
        ).order_by("-acknowledged_at").first()
        if cycle_start and cycle_start.acknowledged_at:
            light_cycle = {
                "started_at": cycle_start.acknowledged_at, "ended_at": last_light_off.acknowledged_at,
                "duration_seconds": max(0, int((last_light_off.acknowledged_at - cycle_start.acknowledged_at).total_seconds())),
                "origin": _command_origin(cycle_start),
            }
    max_irrigations = max((sum(day in item.days_of_week for item in pump_schedules) for day in range(7)), default=0)
    max_light_seconds = max((sum(
        ((datetime.combine(now.date(), item.end_time) - datetime.combine(now.date(), item.start_time)).seconds or 86400)
        for item in light_schedules if day in item.days_of_week
    ) for day in range(7)), default=0)
    next_light = _next_lighting_action(light_schedules, now)
    next_irrigation = snapshot.get("next_irrigation")
    soil = snapshot.get("metrics", {}).get("soil_moisture")
    return {
        "irrigation": {
            "configured": bool(pump_schedules), "active": pump_state,
            "state": pump_confirmation["state"], "last_state": pump_confirmation["last_state"],
            "confirmed_at": pump_confirmation["confirmed_at"], "state_source": pump_confirmation["source"],
            "state_is_recent": pump_confirmation["is_recent"],
            "updating": pump_feedback["updating"],
            "confirmation_failed": pump_feedback["confirmation_failed"],
            "mode": _command_origin(last_pump_on) if pump_state and last_pump_on else ("Automático" if pump_schedules else "Manual"),
            "schedules": pump_schedules, "daily_count": max_irrigations,
            "next_at": next_irrigation[0] if next_irrigation else None,
            "last_at": last_pump_on.acknowledged_at if last_pump_on else None,
            "last_duration_seconds": pump_duration, "last_origin": _command_origin(last_pump_on),
            "remaining_until": pump_end, "soil": soil,
        },
        "lighting": {
            "configured": bool(light_schedules), "active": light_state,
            "state": light_confirmation["state"], "last_state": light_confirmation["last_state"],
            "confirmed_at": light_confirmation["confirmed_at"], "state_source": light_confirmation["source"],
            "state_is_recent": light_confirmation["is_recent"],
            "updating": light_feedback["updating"],
            "confirmation_failed": light_feedback["confirmation_failed"],
            "mode": _command_origin(last_light_on) if light_state and last_light_on else ("Automático" if light_schedules else "Manual"),
            "schedules": light_schedules, "hours_per_day": max_light_seconds / 3600 if max_light_seconds else None,
            "next_at": next_light[0] if next_light else None, "next_action": next_light[1] if next_light else None,
            "current_started_at": last_light_on.acknowledged_at if light_state and last_light_on else None,
            "last_cycle": light_cycle,
        },
    }


def devices_for_garden(garden):
    return Device.objects.filter(
        Q(garden=garden)
        | Q(module__installations__garden=garden, module__installations__removed_at__isnull=True)
    ).select_related("model", "garden").prefetch_related(
        "channels", "credentials", "heartbeats", "channels__irrigation_schedules", "channels__lighting_schedules"
    ).distinct()


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
    for device in devices:
        device.latest_heartbeat = device.heartbeats.order_by("-recorded_at").first()
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
                    "raw": reading.raw, "is_recent": reading.recorded_at >= timezone.now() - timedelta(minutes=10),
                }
    cycles = list(PlantingCycle.objects.filter(
        garden=garden, status=PlantingCycle.Status.ACTIVE
    ).select_related("crop", "cultivar__crop", "module", "cultivation_profile", "nutrition_plan"))
    cycle = cycles[0] if cycles else None
    checkout = None
    if garden.subscription_id:
        checkout = CheckoutRequest.objects.filter(
            user__memberships__organization=garden.organization,
            plan_version=garden.subscription.plan_version,
            status=CheckoutRequest.Status.CONFIRMED,
        ).prefetch_related("selected_crops").order_by("-created_at").first()
    contracted_crops = []
    if checkout:
        contracted_crops = list(checkout.selected_crops.all())
        if not contracted_crops:
            contracted_crops = list({cultivar.crop_id: cultivar.crop for cultivar in checkout.selected_cultures.select_related("crop")}.values())
    actuator_channels = [channel for device in devices for channel in device.channels.all() if channel.kind == "actuator" and channel.is_enabled]
    pump_channel = next((item for item in actuator_channels if item.metric == "pump_state"), None)
    light_channel = next((item for item in actuator_channels if item.metric == "light_state"), None)
    next_irrigation = None
    if pump_channel:
        now = timezone.now()
        candidates = []
        for schedule in pump_channel.irrigation_schedules.filter(enabled=True):
            local_now = now.astimezone(ZoneInfo(schedule.timezone))
            for offset in range(8):
                day = local_now.date() + timedelta(days=offset)
                if day.weekday() not in schedule.days_of_week:
                    continue
                candidate = timezone.make_aware(datetime.combine(day, schedule.start_time), ZoneInfo(schedule.timezone))
                if candidate > now:
                    candidates.append((candidate, schedule))
                    break
        next_irrigation = min(candidates, key=lambda item: item[0]) if candidates else None
    next_lighting = None
    if light_channel:
        now = timezone.now()
        candidates = []
        for schedule in light_channel.lighting_schedules.filter(enabled=True):
            local_now = now.astimezone(ZoneInfo(schedule.timezone))
            for offset in range(8):
                day = local_now.date() + timedelta(days=offset)
                if day.weekday() not in schedule.days_of_week:
                    continue
                candidate = timezone.make_aware(datetime.combine(day, schedule.start_time), ZoneInfo(schedule.timezone))
                if candidate > now:
                    candidates.append((candidate, schedule))
                    break
        next_lighting = min(candidates, key=lambda item: item[0]) if candidates else None
    commands = {}
    for channel in actuator_channels:
        commands[channel.metric] = channel.commands.filter(status="succeeded").order_by("-acknowledged_at").first()
    return {
        "garden": garden,
        "devices": devices,
        "metrics": metrics,
        "cycle": cycle,
        "cycles": cycles,
        "contracted_crops": contracted_crops,
        "controller": next((item for item in devices if item.kind == Device.Kind.CONTROLLER), None),
        "camera": next((item for item in devices if item.kind == Device.Kind.CAMERA), None),
        "pump_channel": pump_channel,
        "light_channel": light_channel,
        "next_irrigation": next_irrigation,
        "next_lighting": next_lighting,
        "actuator_states": commands,
        "next_visit": garden.visits.filter(scheduled_start__gte=timezone.now(), status="scheduled").order_by("scheduled_start").first(),
        "latest_photo": GardenPhoto.objects.filter(garden=garden).first(),
        "alerts": Alert.objects.filter(rule__channel__device__in=devices).select_related("rule")[:5],
        **garden_status(garden),
    }
