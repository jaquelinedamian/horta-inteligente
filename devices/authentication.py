import hmac
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone

from .models import DeviceCredential


def authenticate_device(request):
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Device ").strip()
    if not token:
        token = request.headers.get("X-Device-Key", "").strip()
    try:
        prefix, secret = token.split(".", 1)
    except ValueError:
        return None
    credential = (
        DeviceCredential.objects.select_related("device")
        .filter(key_prefix=prefix, is_active=True)
        .first()
    )
    if not credential or (credential.expires_at and credential.expires_at <= timezone.now()):
        return None
    if not hmac.compare_digest(credential.secret_hash, DeviceCredential.hash_secret(secret)):
        return None
    credential.last_used_at = timezone.now()
    credential.save(update_fields=["last_used_at", "updated_at"])
    return credential.device


def device_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        device = authenticate_device(request)
        if not device:
            return JsonResponse({"error": "invalid_device_credentials"}, status=401)
        request.device = device
        return view(request, *args, **kwargs)
    return wrapped
