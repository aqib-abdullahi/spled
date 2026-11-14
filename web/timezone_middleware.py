from zoneinfo import ZoneInfo

from django.utils import timezone


class UserTimezoneMiddleware:
    """Show times in the signed-in person's own time zone."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        name = user.time_zone if user is not None and user.is_authenticated else ""
        try:
            if name:
                timezone.activate(ZoneInfo(name))
        except (KeyError, ValueError, OSError):
            # An unknown or malformed zone name (ZoneInfoNotFoundError is a KeyError)
            # falls back to the default zone instead of breaking the page.
            pass
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()