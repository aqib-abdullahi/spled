from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.models import User
from security.throttle import clear, hit, limited

from .profile_forms import ChangePasswordForm, ProfileForm

LOCKED = "Too many attempts. Wait a few minutes, then try again."


def _page(request, profile_form=None, password_form=None, password_error="", status=200):
    if profile_form is None:
        profile_form = ProfileForm(instance=User.objects.get(pk=request.user.pk))
    if password_form is None:
        password_form = ChangePasswordForm(request.user)
    return render(request, "profile.html", {
        "active": "profile",
        "profile_form": profile_form,
        "password_form": password_form,
        "password_error": password_error,
    }, status=status)


@login_required
@never_cache
def profile_page(request):
    return _page(request)


@login_required
@require_POST
def profile_save(request):
    # Edit a fresh copy, so a rejected form can't alter the signed-in user object.
    form = ProfileForm(request.POST, instance=User.objects.get(pk=request.user.pk))
    if form.is_valid():
        form.save()
        messages.success(request, "Your details were saved.")
        return redirect("profile")
    return _page(request, profile_form=form)


@login_required
@require_POST
def profile_password(request):
    user = request.user
    if limited("password_user", user.pk):
        return _page(request, password_error=LOCKED, status=429)
    form = ChangePasswordForm(user, request.POST)
    if form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)  # stay signed in here; other devices are signed out
        clear("password_user", user.pk)
        send_mail(
            "Your Spled password was changed",
            f"Hi {user.full_name},\n\nThe password for your Spled account was just changed. "
            "Every other device has been signed out.\n\nIf this wasn’t you, reset your password "
            "straight away and tell your administrator.",
            None,
            [user.email],
        )
        messages.success(request, "Your password was changed. Other devices have been signed out.")
        return redirect("profile")
    if "old_password" in form.errors:
        hit("password_user", user.pk)
    return _page(request, password_form=form)