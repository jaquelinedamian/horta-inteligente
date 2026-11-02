from datetime import datetime, time, timedelta
from collections.abc import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from accounts.models import Membership, User
from devices.selectors import actuator_automation_summary
from gardens.configuration import effective_garden_configuration

from .forms import IrrigationScheduleForm, LightingScheduleForm


WEEKDAY_SHORT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
WEEKDAY_LONG = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")


def can_operate_automation(user, garden):
    return bool(
        user.is_authenticated
        and (
            user.is_hortaviva_admin
            or user.employee_role == User.EmployeeRole.TECHNICIAN
            or user.memberships.filter(
                organization=garden.organization,
                is_active=True,
                role__in=[Membership.Role.OWNER, Membership.Role.MANAGER],
            ).exists()
        )
    )


def can_edit_automation(user, garden):
    # Mantém exatamente a regra operacional já usada pelos endpoints atuais.
    return can_operate_automation(user, garden)


def format_weekdays(days):
    normalized = sorted({int(day) for day in (days or []) if str(day).isdigit() and 0 <= int(day) <= 6})
    if normalized == list(range(7)):
        return "Todos os dias"
    if normalized == list(range(5)):
        return "Seg–Sex"
    if normalized == [5, 6]:
        return "Sáb–Dom"
    return ", ".join(WEEKDAY_SHORT[day] for day in normalized) or "Dias não definidos"


def _parse_clock(value):
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _schedule_events(schedules, *, event_fields):
    now = timezone.now()
    candidates = []
    for item in schedules:
        try:
            zone = ZoneInfo(item.get("timezone") or str(timezone.get_current_timezone()))
        except ZoneInfoNotFoundError:
            zone = timezone.get_current_timezone()
        local_now = timezone.localtime(now, zone)
        days = item.get("days") or list(range(7))
        for field, action in event_fields:
            clock = _parse_clock(item.get(field))
            if not clock:
                continue
            # Inclui ontem para capturar o desligamento de períodos que
            # atravessam a meia-noite.
            for offset in range(-1, 8):
                day = local_now.date() + timedelta(days=offset)
                event_day = day
                if field == "end":
                    start = _parse_clock(item.get("start"))
                    if start and clock <= start:
                        event_day += timedelta(days=1)
                if day.weekday() not in days:
                    continue
                at = timezone.make_aware(datetime.combine(event_day, clock), zone)
                if at > now:
                    candidates.append((at, action))
                    break
    return min(candidates, key=lambda event: event[0]) if candidates else None


def _friendly_event(event, *, empty):
    if not event:
        return empty
    at, action = event
    local_at = timezone.localtime(at)
    today = timezone.localdate()
    if local_at.date() == today:
        day = "hoje"
    elif local_at.date() == today + timedelta(days=1):
        day = "amanhã"
    else:
        day = WEEKDAY_LONG[local_at.weekday()]
    prefix = f"{action} " if action else ""
    return f"{prefix}{day} às {local_at:%H:%M}"


def _lighting_hours(schedules):
    totals = []
    for weekday in range(7):
        seconds = sum(
            int(item.get("duration_seconds") or 0)
            for item in schedules if weekday in (item.get("days") or list(range(7)))
        )
        totals.append(seconds)
    maximum = max(totals, default=0)
    return maximum / 3600 if maximum else None


def automation_panel_context(*, user, garden, snapshot, next_url):
    config = effective_garden_configuration(garden)
    summary = actuator_automation_summary(snapshot)
    irrigation = config.get("irrigation", {}) if isinstance(config.get("irrigation"), Mapping) else {}
    lighting = config.get("lighting", {}) if isinstance(config.get("lighting"), Mapping) else {}
    irrigation_schedules = [item for item in irrigation.get("schedules", []) if item.get("enabled")]
    lighting_schedules = [item for item in lighting.get("schedules", []) if item.get("enabled")]
    irrigation_event = _schedule_events(irrigation_schedules, event_fields=(("time", ""),))
    lighting_event = _schedule_events(lighting_schedules, event_fields=(("start", "Ligar"), ("end", "Desligar")))

    summary["irrigation"].update(
        schedule_rows=[{
            **item, "days_label": format_weekdays(item.get("days")),
        } for item in irrigation_schedules],
        next_at=irrigation_event[0] if irrigation_event else None,
        next_label=_friendly_event(irrigation_event, empty="Nenhuma irrigação programada"),
        duration_seconds=(irrigation.get("duration_seconds") or irrigation.get("pump_duration_seconds") or 10),
        frequency_count=irrigation.get("frequency_count"),
        frequency_period=irrigation.get("frequency_period"),
    )
    summary["lighting"].update(
        schedule_rows=[{
            **item, "days_label": format_weekdays(item.get("days")),
        } for item in lighting_schedules],
        next_at=lighting_event[0] if lighting_event else None,
        next_action=lighting_event[1] if lighting_event else None,
        next_label=_friendly_event(lighting_event, empty="Não agendada"),
        hours_per_day=_lighting_hours(lighting_schedules),
        source_label=lighting.get("source_label"),
    )

    pump = snapshot.get("pump_channel")
    light = snapshot.get("light_channel")
    pump_channel_valid = bool(
        pump and pump.key == "pump" and pump.metric == "pump_state" and pump.is_enabled
    )
    light_channel_valid = bool(
        light and light.key == "grow-light" and light.metric == "light_state" and light.is_enabled
    )
    return {
        "garden": garden,
        "snapshot": snapshot,
        "summary": summary,
        "can_operate": can_operate_automation(user, garden),
        "can_edit": can_edit_automation(user, garden),
        "next_url": next_url,
        "pump_channel_valid": pump_channel_valid,
        "light_channel_valid": light_channel_valid,
        "irrigation_add_form": IrrigationScheduleForm(auto_id=f"irrigation-{garden.pk}-%s"),
        "lighting_add_form": LightingScheduleForm(auto_id=f"lighting-{garden.pk}-%s"),
        "irrigation_edit_rows": [
            {"schedule": item, "form": IrrigationScheduleForm(instance=item, auto_id=f"irrigation-{item.pk}-%s")}
            for item in (pump.irrigation_schedules.order_by("start_time") if pump else [])
        ],
        "lighting_edit_rows": [
            {"schedule": item, "form": LightingScheduleForm(instance=item, auto_id=f"lighting-{item.pk}-%s")}
            for item in (light.lighting_schedules.order_by("start_time") if light else [])
        ],
    }
