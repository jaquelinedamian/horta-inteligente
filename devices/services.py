from datetime import timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Alert, AlertRule, Channel, DeviceCommand, TelemetryReading


def parsed_datetime(value, field_name="recorded_at"):
    parsed = parse_datetime(value or "")
    if not parsed:
        raise ValueError(f"{field_name} deve ser uma data ISO-8601 válida")
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


def reading_values(channel, value):
    fields = {"decimal_value": None, "boolean_value": None, "text_value": ""}
    if channel.value_type in (Channel.ValueType.DECIMAL, Channel.ValueType.INTEGER):
        try:
            fields["decimal_value"] = Decimal(str(value))
        except (InvalidOperation, TypeError):
            raise ValueError(f"valor inválido para o canal {channel.key}")
    elif channel.value_type == Channel.ValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValueError(f"valor booleano inválido para o canal {channel.key}")
        fields["boolean_value"] = value
    else:
        fields["text_value"] = str(value)
    return fields


def evaluate_alerts(reading):
    if reading.decimal_value is None:
        return
    operations = {
        AlertRule.Operator.LT: lambda a, b: a < b,
        AlertRule.Operator.LTE: lambda a, b: a <= b,
        AlertRule.Operator.GT: lambda a, b: a > b,
        AlertRule.Operator.GTE: lambda a, b: a >= b,
        AlertRule.Operator.EQ: lambda a, b: a == b,
    }
    for rule in reading.channel.alert_rules.filter(is_active=True):
        if operations[rule.operator](reading.decimal_value, rule.threshold):
            cooldown_start = reading.received_at - timedelta(seconds=rule.cooldown_seconds)
            if rule.alerts.filter(status=Alert.Status.OPEN, opened_at__gte=cooldown_start).exists():
                continue
            Alert.objects.create(
                rule=rule,
                reading=reading,
                message=f"{reading.channel.name}: {reading.decimal_value} {reading.channel.unit}",
                opened_at=reading.received_at,
            )


@transaction.atomic
def ingest_readings(device, readings):
    channels = {c.key: c for c in device.channels.filter(kind=Channel.Kind.SENSOR, is_enabled=True)}
    results = []
    for item in readings:
        channel = channels.get(item.get("channel"))
        if not channel:
            raise ValueError(f"canal desconhecido ou desabilitado: {item.get('channel')}")
        key = str(item.get("idempotency_key", "")).strip()
        if not key:
            raise ValueError("idempotency_key é obrigatório")
        defaults = {
            "recorded_at": parsed_datetime(item.get("recorded_at")),
            "quality": item.get("quality", "good"),
            "raw": item.get("raw", {}),
            **reading_values(channel, item.get("value")),
        }
        reading, created = TelemetryReading.objects.get_or_create(
            channel=channel, idempotency_key=key, defaults=defaults
        )
        if created:
            evaluate_alerts(reading)
        results.append({"id": str(reading.id), "created": created})
    device.last_seen_at = timezone.now()
    device.status = device.Status.ONLINE
    device.save(update_fields=["last_seen_at", "status", "updated_at"])
    return results


@transaction.atomic
def pending_commands(device, limit=20):
    now = timezone.now()
    commands = list(
        DeviceCommand.objects.select_for_update()
        .filter(device=device, status=DeviceCommand.Status.PENDING)
        .filter(Q(not_before__isnull=True) | Q(not_before__lte=now))
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))[:limit]
    )
    for command in commands:
        command.status = DeviceCommand.Status.DELIVERED
        command.delivered_at = now
        command.save(update_fields=["status", "delivered_at", "updated_at"])
    return commands


def schedule_lighting(now=None):
    """Materializa o estado desejado das luzes como comandos idempotentes."""
    from .models import LightingSchedule

    now = now or timezone.now()
    created = 0
    for schedule in LightingSchedule.objects.filter(enabled=True, actuator__is_enabled=True).select_related("actuator__device"):
        local = now.astimezone(ZoneInfo(schedule.timezone))
        enabled_today = local.weekday() in schedule.days_of_week
        if schedule.start_time <= schedule.end_time:
            should_be_on = enabled_today and schedule.start_time <= local.time() < schedule.end_time
        else:
            previous_day = (local.weekday() - 1) % 7
            should_be_on = (
                (enabled_today and local.time() >= schedule.start_time)
                or (previous_day in schedule.days_of_week and local.time() < schedule.end_time)
            )
        bucket = local.strftime("%Y%m%d%H%M")
        _, was_created = DeviceCommand.objects.get_or_create(
            device=schedule.actuator.device,
            idempotency_key=f"lighting:{schedule.id}:{bucket}",
            defaults={
                "channel": schedule.actuator,
                "command_type": "set_state",
                "payload": {"on": should_be_on, "source": "lighting_schedule"},
            },
        )
        created += int(was_created)
    return created
