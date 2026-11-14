import hashlib
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Attempt

# scope: (how many, within how many seconds)
DEFAULT_RULES = {
    "signin_pair": (5, 15 * 60),    # failures for one address + email
    "signin_ip": (30, 15 * 60),     # failures from one address
    "signup_ip": (10, 60 * 60),     # completed sign-ups from one address
    "email_ip": (10, 60 * 60),      # emails requested from one address
    "email_target": (5, 60 * 60),   # emails sent to one email address
}


def rule(scope):
    overrides = getattr(settings, "SPLED_LIMITS", None) or {}
    return overrides.get(scope, DEFAULT_RULES[scope])  # unknown scope: KeyError


def _hash(key):
    return hashlib.sha256(str(key).strip().lower().encode("utf-8")).hexdigest()


def count(scope, key):
    _, window = rule(scope)
    since = timezone.now() - timedelta(seconds=window)
    return Attempt.objects.filter(
        scope=scope, key_hash=_hash(key), created_at__gte=since
    ).count()


def limited(scope, key):
    limit, _ = rule(scope)
    return count(scope, key) >= limit


def hit(scope, key):
    rule(scope)
    Attempt.objects.create(scope=scope, key_hash=_hash(key))


def clear(scope, key):
    Attempt.objects.filter(scope=scope, key_hash=_hash(key)).delete()


def client_ip(request):
    """The caller's address. Forwarding headers are trusted only when
    TRUSTED_PROXY_COUNT says how many proxies sit in front of us, and then only
    the entry those proxies added, never one the caller could have supplied."""
    address = request.META.get("REMOTE_ADDR") or "unknown"
    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    if proxies:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) >= proxies:
            return parts[-proxies]
    return address

DEFAULT_RULES.update(
    {
        "twofactor_user": (5, 15 * 60),  # wrong codes for one account
        "twofactor_ip": (30, 15 * 60),   # wrong codes from one address
    }
)


DEFAULT_RULES.update(
    {
        "password_user": (5, 15 * 60),  # wrong current passwords for one account
    }
)
