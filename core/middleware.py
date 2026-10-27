import logging
from time import monotonic


logger = logging.getLogger(__name__)


class ServerTimingMiddleware:
    """Registra e expõe somente duração, sem headers, tokens ou payloads."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = monotonic()
        response = self.get_response(request)
        duration_ms = (monotonic() - started) * 1000
        response["Server-Timing"] = f"app;dur={duration_ms:.1f}"
        if request.path.startswith(("/api/v1/device/", "/api/device/", "/app/dispositivo/")):
            logger.info(
                "request_timing method=%s path=%s status=%s app_duration_ms=%.1f",
                request.method, request.path, response.status_code, duration_ms,
            )
        return response
