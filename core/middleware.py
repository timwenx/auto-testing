import logging
import re
import time

logger = logging.getLogger(__name__)


class DisableCSRFMiddleware:
    """Disable CSRF for API endpoints (all /api/ paths)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/'):
            setattr(request, '_dont_enforce_csrf_checks', True)
        return self.get_response(request)


class RequestLoggingMiddleware:
    """Log API requests with useful context instead of raw HTTP lines."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        duration = (time.time() - start) * 1000

        if request.path.startswith('/api/'):
            level = logging.DEBUG if request.method == 'GET' else logging.INFO
            logger.log(
                level,
                '%s %s → %s (%.0fms)',
                request.method,
                request.path,
                response.status_code,
                duration,
            )
        return response
