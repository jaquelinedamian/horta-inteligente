import json

from django.db import transaction
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .authentication import device_required
from gardens.configuration import effective_garden_configuration
from .models import Channel, DeviceCommand, DeviceHeartbeat, GardenPhoto
from .services import ingest_readings, parsed_datetime, pending_commands


def json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("JSON inválido")


def api_error(message, status=400):
    return JsonResponse({"error": "invalid_request", "detail": str(message)}, status=status)


def validate_device_id(request, payload=None):
    supplied = request.headers.get("X-Device-ID", "").strip()
    if not supplied and payload:
        supplied = str(payload.get("device_id", "")).strip()
    if not supplied:
        raise ValueError("device_id é obrigatório")
    if supplied != request.device.serial_number:
        raise PermissionError("device_id não corresponde ao token")


def device_garden(device):
    garden = device.assigned_garden()
    if not garden:
        raise ValueError("dispositivo ainda não está vinculado a uma horta")
    return garden


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


@csrf_exempt
@require_POST
@device_required
def telemetry_v2(request):
    """API simplificada; converte o payload plano para os canais existentes."""
    try:
        payload = json_body(request)
        validate_device_id(request, payload)
        recorded_at = payload.get("recorded_at") or timezone.now().isoformat()
        aliases = {
            "temperature": "air_temperature", "humidity": "air_humidity",
            "pressure": "air_pressure", "water_level": "water_level",
            "pump": "pump_state", "light": "light_state",
        }
        channels = {channel.metric: channel for channel in request.device.channels.filter(is_enabled=True)}
        readings = []
        message_id = str(payload.get("idempotency_key") or f"{request.device.id}:{recorded_at}")
        for field, metric in aliases.items():
            channel = channels.get(metric)
            if field in payload and channel and channel.kind == Channel.Kind.SENSOR:
                readings.append({
                    "channel": channel.key, "value": payload[field], "recorded_at": recorded_at,
                    "idempotency_key": f"{message_id}:{field}", "raw": payload,
                })
        if not readings:
            raise ValueError("nenhuma métrica conhecida corresponde aos canais do dispositivo")
        return JsonResponse({"device_id": request.device.serial_number, "readings": ingest_readings(request.device, readings)}, status=202)
    except PermissionError as exc:
        return JsonResponse({"error": "device_mismatch", "detail": str(exc)}, status=403)
    except ValueError as exc:
        return api_error(exc)


@csrf_exempt
@require_POST
@device_required
def photo(request):
    try:
        validate_device_id(request, request.POST)
        if request.device.kind != request.device.Kind.CAMERA:
            raise PermissionError("a credencial não pertence a uma câmera")
        upload = request.FILES.get("photo")
        content_type = upload.content_type if upload else request.content_type
        data = upload.read() if upload else request.body
        limit = getattr(settings, "DEVICE_PHOTO_MAX_BYTES", 5 * 1024 * 1024)
        if content_type not in ("image/jpeg", "image/jpg") or not data.startswith(b"\xff\xd8"):
            raise ValueError("envie uma imagem JPEG válida")
        if not data or len(data) > limit:
            raise ValueError(f"imagem excede o limite de {limit} bytes")
        captured_raw = request.POST.get("captured_at") or request.headers.get("X-Captured-At")
        captured_at = parsed_datetime(captured_raw) if captured_raw else timezone.now()
        garden = device_garden(request.device)
        item = GardenPhoto.objects.create(
            garden=garden, device=request.device, captured_at=captured_at,
            image_data=data, content_type="image/jpeg", byte_size=len(data),
        )
        request.device.last_seen_at = timezone.now()
        request.device.status = request.device.Status.ONLINE
        request.device.save(update_fields=["last_seen_at", "status", "updated_at"])
        return JsonResponse({"id": str(item.id), "captured_at": item.captured_at.isoformat()}, status=201)
    except PermissionError as exc:
        return JsonResponse({"error": "device_mismatch", "detail": str(exc)}, status=403)
    except ValueError as exc:
        return api_error(exc)


@require_GET
@device_required
def configuration(request):
    try:
        validate_device_id(request)
        garden = device_garden(request.device)
        return JsonResponse(effective_garden_configuration(garden))
    except PermissionError as exc:
        return JsonResponse({"error": "device_mismatch", "detail": str(exc)}, status=403)
    except ValueError as exc:
        return api_error(exc, 409)
