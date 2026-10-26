import hmac
import logging
from functools import wraps

from django.http import JsonResponse
from django.utils import timezone

from .models import DeviceCredential


logger = logging.getLogger(__name__)


def _log_auth_failure(request, reason, **details):
    logger.warning(
        "device_auth_failed path=%s reason=%s %s",
        request.path,
        reason,
        " ".join(f"{key}={value}" for key, value in details.items()),
    )


def authenticate_device(request):
    authorization = request.headers.get("Authorization", "").strip()
    scheme, separator, value = authorization.partition(" ")
    header_present = bool(authorization)

    if header_present and (not separator or scheme.casefold() != "device"):
        _log_auth_failure(
            request,
            "invalid_scheme",
            authorization_present=True,
            scheme=scheme or "missing",
            token_length=len(value.strip()),
        )
        return None

    token = value.strip() if header_present else request.headers.get("X-Device-Key", "").strip()
    source = "authorization" if header_present else "x_device_key"

    if not token:
        _log_auth_failure(
            request,
            "missing_token",
            authorization_present=header_present,
            scheme=scheme or "missing",
            source=source,
        )
        return None

    try:
        prefix, secret = token.split(".", 1)
    except ValueError:
        _log_auth_failure(
            request,
            "missing_separator",
            authorization_present=header_present,
            scheme=scheme or "Device",
            source=source,
            token_length=len(token),
        )
        return None

    if not prefix or not secret or "." in secret:
        _log_auth_failure(
            request,
            "invalid_token_format",
            authorization_present=header_present,
            scheme=scheme or "Device",
            source=source,
            prefix=prefix or "missing",
            token_length=len(token),
        )
        return None

    credentials = list(
        DeviceCredential.objects.select_related("device")
        .filter(key_prefix=prefix)
    )

    if not credentials:
        _log_auth_failure(
            request,
            "prefix_not_found",
            authorization_present=header_present,
            scheme=scheme or "Device",
            source=source,
            prefix=prefix,
            token_length=len(token),
        )
        return None

    received_hash = DeviceCredential.hash_secret(secret)
    credential = next(
        (
            item for item in credentials
            if hmac.compare_digest(item.secret_hash, received_hash)
        ),
        None,
    )

    if not credential:
        _log_auth_failure(
            request,
            "secret_hash_mismatch",
            authorization_present=header_present,
            scheme=scheme or "Device",
            source=source,
            prefix=prefix,
            token_length=len(token),
            credential_count=len(credentials),
            active_any=any(item.is_active for item in credentials),
        )
        return None

    supplied_device_id = request.headers.get("X-Device-ID", "").strip()
    device_id_matches = not supplied_device_id or supplied_device_id == str(credential.device_id)

    if not credential.is_active:
        _log_auth_failure(
            request,
            "inactive_credential",
            prefix=prefix,
            token_length=len(token),
            device_id=credential.device_id,
            supplied_device_id=supplied_device_id or "missing",
            device_id_matches=device_id_matches,
        )
        return None

    if credential.expires_at and credential.expires_at <= timezone.now():
        _log_auth_failure(
            request,
            "expired_credential",
            prefix=prefix,
            token_length=len(token),
            device_id=credential.device_id,
            supplied_device_id=supplied_device_id or "missing",
            device_id_matches=device_id_matches,
        )
        return None

    credential.last_used_at = timezone.now()
    credential.save(update_fields=["last_used_at", "updated_at"])

    logger.info(
        "device_auth_succeeded path=%s scheme=%s source=%s prefix=%s "
        "token_length=%s credential_active=%s device_id=%s "
        "supplied_device_id=%s device_id_matches=%s",
        request.path,
        scheme or "Device",
        source,
        prefix,
        len(token),
        credential.is_active,
        credential.device_id,
        supplied_device_id or "missing",
        device_id_matches,
    )

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
