from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode


def admin_login(request):
    """Django's own admin login only checks a password. Send everyone through
    our sign-in instead, so the second step can't be skipped."""
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("/admin/")
        raise PermissionDenied
    target = request.GET.get("next", "/admin/")
    if not url_has_allowed_host_and_scheme(
        target, {request.get_host()}, require_https=request.is_secure()
    ):
        target = "/admin/"
    return redirect(f"{reverse('signin')}?{urlencode({'next': target})}")