import logging

from django.db import connection
from django.http import HttpResponse
from django.views.decorators.http import require_safe

logger = logging.getLogger(__name__)


@require_safe
def healthz(request):
    """Is the app up, and can it reach its database? For monitors and load balancers.

    The answer is deliberately tiny: no versions, settings, counts or error details.
    The real error goes to the server log, not to whoever asked.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("Health check failed: database unreachable")
        response = HttpResponse("database unavailable", content_type="text/plain", status=503)
    else:
        response = HttpResponse("ok", content_type="text/plain")
    response["Cache-Control"] = "no-store"
    return response


@require_safe
def livez(request):
    """Is the process up? Touches nothing else, so a database outage never makes a host
    restart a healthy app. /healthz/ is the check that includes the database."""
    response = HttpResponse("ok", content_type="text/plain")
    response["Cache-Control"] = "no-store"
    return response
