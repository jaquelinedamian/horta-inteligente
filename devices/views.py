import json

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .authentication import device_required
from .models import DeviceCommand, DeviceHeartbeat
from .services import ingest_readings, parsed_datetime, pending_commands


def json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("JSON inválido")


def api_error(message, status=400):
    return JsonResponse({"error": "invalid_request", "detail": str(message)}, status=status)


@csrf_exempt
@require_POST
@device_required
def telemetry(request):
    try:
        payload = json_body(request)
        readings = payload.get("readings")
        if not isinstance(readings, list) or not readings:
            raise ValueError("readings deve ser uma lista não vazia")
        return JsonResponse({"readings": ingest_readings(request.device, readings)}, status=202)
    except ValueError as exc:
        return api_error(exc)


@csrf_exempt
@require_POST
@device_required
def heartbeat(request):
    try:
        payload = json_body(request)
        beat = DeviceHeartbeat.objects.create(
            device=request.device,
            recorded_at=parsed_datetime(payload.get("recorded_at")),
            uptime_seconds=payload.get("uptime_seconds"),
            signal_strength=payload.get("signal_strength"),
            free_heap_bytes=payload.get("free_heap_bytes"),
            firmware_version=payload.get("firmware_version", ""),
            diagnostics=payload.get("diagnostics", {}),
        )
        request.device.last_seen_at = timezone.now()
        request.device.status = request.device.Status.ONLINE
        request.device.firmware_version = beat.firmware_version or request.device.firmware_version
        request.device.save(update_fields=["last_seen_at", "status", "firmware_version", "updated_at"])
        return JsonResponse({"id": str(beat.id)}, status=202)
    except ValueError as exc:
        return api_error(exc)


@require_GET
@device_required
def commands(request):
    items = pending_commands(request.device)
    return JsonResponse({"commands": [
        {
            "id": str(command.id),
            "channel": command.channel.key if command.channel else None,
            "type": command.command_type,
            "payload": command.payload,
            "expires_at": command.expires_at.isoformat() if command.expires_at else None,
        } for command in items
    ]})


@csrf_exempt
@require_POST
@device_required
@transaction.atomic
def acknowledge_command(request, command_id):
    try:
        payload = json_body(request)
        status = payload.get("status")
        allowed = {DeviceCommand.Status.SUCCEEDED, DeviceCommand.Status.FAILED}
        if status not in allowed:
            raise ValueError("status deve ser succeeded ou failed")
        command = DeviceCommand.objects.select_for_update().filter(id=command_id, device=request.device).first()
        if not command:
            return api_error("comando não encontrado", 404)
        if command.status not in {DeviceCommand.Status.DELIVERED, *allowed}:
            return api_error("comando não está aguardando confirmação", 409)
        command.status = status
        command.result = payload.get("result", {})
        command.acknowledged_at = timezone.now()
        command.save(update_fields=["status", "result", "acknowledged_at", "updated_at"])
        return JsonResponse({"id": str(command.id), "status": command.status})
    except ValueError as exc:
        return api_error(exc)
