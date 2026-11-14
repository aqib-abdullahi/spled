import time

from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.models import User
from security.throttle import clear, client_ip, hit, limited
from twofactor.models import TwoFactor
from twofactor.services import (
    begin_setup,
    confirm_setup,
    disable,
    format_secret,
    generate_backup_codes,
    has_two_factor,
    looks_like_a_code,
    qr_data_uri,
    remaining_backup_codes,
    verify_code,
)
from twofactor.totp import provisioning_uri

from .signup_forms import SignInForm

PENDING = "pending_2fa"
PENDING_MAX_AGE = 10 * 60


class CodeForm(forms.Form):
    code = forms.CharField(
        max_length=32,
        widget=forms.TextInput(attrs={
            "autocomplete": "one-time-code", "autofocus": True,
            "spellcheck": "false", "autocapitalize": "off",
        }),
    )


class ConfirmForm(forms.Form):
    password = forms.CharField(strip=False, max_length=128)
    code = forms.CharField(max_length=32)


def _notify(user, subject, text):
    send_mail(
        subject,
        f"Hi {user.full_name},\n\n{text}\n\nIf this wasn’t you, reset your password "
        "straight away and tell your administrator.",
        None,
        [user.email],
    )


def _safe_next(request, url):
    if url and url_has_allowed_host_and_scheme(
        url, {request.get_host()}, require_https=request.is_secure()
    ):
        return url
    return "/app/"


# ---------- Sign-in: the second step ----------

class TwoFactorLoginView(LoginView):
    template_name = "sign_in.html"
    redirect_authenticated_user = True
    authentication_form = SignInForm

    def form_valid(self, form):
        user = form.get_user()
        if has_two_factor(user):
            self.request.session[PENDING] = {
                "uid": user.pk,
                "backend": user.backend,
                "next": self.get_success_url(),
                "at": time.time(),
            }
            return redirect("signin_verify")
        return super().form_valid(form)


def verify_signin(request):
    pending = request.session.get(PENDING)
    if not pending or time.time() - pending.get("at", 0) > PENDING_MAX_AGE:
        request.session.pop(PENDING, None)
        return redirect("signin")
    user = User.objects.filter(pk=pending["uid"], is_active=True).first()
    if user is None or not has_two_factor(user):
        request.session.pop(PENDING, None)
        return redirect("signin")

    error = ""
    form = CodeForm()
    if request.method == "POST":
        ip = client_ip(request)
        if limited("twofactor_user", user.pk) or limited("twofactor_ip", ip):
            response = render(request, "throttled.html", status=429)
            response["Retry-After"] = "900"
            return response
        form = CodeForm(request.POST)
        if form.is_valid() and looks_like_a_code(form.cleaned_data["code"]):
            kind = verify_code(user, form.cleaned_data["code"])
            if kind:
                clear("twofactor_user", user.pk)
                request.session.pop(PENDING, None)
                login(request, user, backend=pending["backend"])
                if kind == "backup":
                    _notify(
                        user, "A backup code was used to sign in",
                        "One of your backup codes was just used to sign in to Spled.",
                    )
                return redirect(_safe_next(request, pending.get("next")))
            hit("twofactor_user", user.pk)
            hit("twofactor_ip", ip)
            error = "That code isn’t right."
        else:
            error = (
                "Enter the 6-digit code from your authenticator app, "
                "or one of your backup codes."
            )
    return render(request, "signin_verify.html", {"form": form, "error": error})


# ---------- Account security ----------

def _context(request):
    tf = TwoFactor.objects.filter(user=request.user, confirmed_at__isnull=False).first()
    remaining = remaining_backup_codes(request.user) if tf else 0
    return {
        "active": "security", "enabled": tf is not None,
        "remaining": remaining, "low": tf is not None and remaining <= 2,
    }


def _codes_page(request, codes, first_time):
    response = render(request, "twofactor_codes.html", {
        "active": "security", "codes": codes, "first_time": first_time,
    })
    response["Cache-Control"] = "no-store"
    return response


def _reauthenticate(request):
    """Check the password and a current code. Returns an error message, or None."""
    user = request.user
    ip = client_ip(request)
    if limited("twofactor_user", user.pk) or limited("twofactor_ip", ip):
        return "Too many attempts. Wait a few minutes, then try again."
    form = ConfirmForm(request.POST)
    if not form.is_valid():
        return "Enter your password and a code."
    d = form.cleaned_data
    if user.check_password(d["password"]) and verify_code(user, d["code"]):
        clear("twofactor_user", user.pk)
        return None
    hit("twofactor_user", user.pk)
    hit("twofactor_ip", ip)
    return "Your password or code isn’t right."


@login_required
@never_cache
def account_security(request):
    return render(request, "account_security.html", _context(request))


@login_required
@never_cache
def twofactor_setup(request):
    if has_two_factor(request.user):
        return redirect("account_security")
    tf = begin_setup(request.user)
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        codes = confirm_setup(request.user, form.cleaned_data["code"])
        if codes:
            _notify(
                request.user, "Two-step verification turned on",
                "Two-step verification was turned on for your Spled account.",
            )
            return _codes_page(request, codes, first_time=True)
        form.add_error(
            "code", "That code isn’t right. Check the time on your phone, then try the next code."
        )
    uri = provisioning_uri(tf.secret, request.user.email)
    return render(request, "twofactor_setup.html", {
        "active": "security", "form": form, "uri": uri,
        "secret": format_secret(tf.secret), "qr": qr_data_uri(uri),
    })


@login_required
@require_POST
def twofactor_disable(request):
    if not has_two_factor(request.user):
        return redirect("account_security")
    error = _reauthenticate(request)
    if error:
        return render(request, "account_security.html", {
            **_context(request), "confirm_error": error, "open_section": "disable",
        })
    disable(request.user)
    _notify(
        request.user, "Two-step verification turned off",
        "Two-step verification was turned off for your Spled account.",
    )
    messages.success(request, "Two-step verification is off.")
    return redirect("account_security")


@login_required
@require_POST
def twofactor_new_codes(request):
    if not has_two_factor(request.user):
        return redirect("account_security")
    error = _reauthenticate(request)
    if error:
        return render(request, "account_security.html", {
            **_context(request), "confirm_error": error, "open_section": "codes",
        })
    codes = generate_backup_codes(request.user)
    _notify(
        request.user, "New backup codes generated",
        "New backup codes were generated for your Spled account. Your old ones no longer work.",
    )
    return _codes_page(request, codes, first_time=False)