from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from organisations.models import Membership, Organisation

from .signup_forms import ResendForm, SignUpForm

VERIFY_SALT = "spled.email-verify"


def _max_age():
    return getattr(settings, "EMAIL_VERIFY_MAX_AGE", 3 * 24 * 60 * 60)


def _send_verification(request, user):
    token = signing.dumps({"u": user.pk, "e": user.email}, salt=VERIFY_SALT)
    link = request.build_absolute_uri(reverse("verify_email", args=[token]))
    days = max(1, _max_age() // 86400)
    send_mail(
        "Verify your email for Spled",
        f"Hi {user.full_name},\n\n"
        "Open this link to verify your email address and finish setting up "
        f"your Spled account. It expires in {days} days:\n\n{link}\n\n"
        "If you didn’t sign up, you can ignore this email.",
        None,
        [user.email],
    )


def _send_already_registered(request, user):
    signin = request.build_absolute_uri(reverse("signin"))
    reset = request.build_absolute_uri(reverse("password_reset"))
    send_mail(
        "You already have a Spled account",
        f"Hi {user.full_name},\n\n"
        "Someone used this email address to sign up for Spled, but you "
        f"already have an account.\n\nSign in: {signin}\n"
        f"Forgot your password? {reset}\n\n"
        "If that wasn’t you, you can ignore this email.",
        None,
        [user.email],
    )


def sign_up(request):
    if request.user.is_authenticated:
        return redirect("overview")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        existing = User.objects.filter(email__iexact=d["email"]).first()
        if existing is None:
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        d["email"], d["password1"],
                        full_name=d["full_name"], is_active=False,
                    )
                    org = Organisation.objects.create(
                        name=d["organisation_name"], kind=d["kind"]
                    )
                    Membership.objects.create(
                        user=user, organisation=org, role=Membership.Role.ADMIN
                    )
            except IntegrityError:  # someone signed up with it a moment ago
                existing = User.objects.filter(email__iexact=d["email"]).first()
            else:
                _send_verification(request, user)
        if existing is not None:
            if not existing.is_active and not existing.email_verified_at:
                _send_verification(request, existing)
            else:
                _send_already_registered(request, existing)
        return redirect("signup_sent")
    return render(request, "sign_up.html", {"form": form})


def signup_sent(request):
    return render(request, "check_email.html")


def verify_email(request, token):
    try:
        data = signing.loads(token, salt=VERIFY_SALT, max_age=_max_age())
        user = User.objects.get(pk=data["u"], email__iexact=data["e"])
    except (signing.BadSignature, User.DoesNotExist, KeyError, TypeError, ValueError):
        return render(request, "verify_email.html", {"state": "invalid"})
    if user.email_verified_at:
        return render(request, "verify_email.html", {"state": "already"})
    user.is_active = True
    user.email_verified_at = timezone.now()
    user.save(update_fields=["is_active", "email_verified_at"])
    return render(request, "verify_email.html", {"state": "ok"})


def resend_verification(request):
    form = ResendForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = User.objects.filter(
            email__iexact=form.cleaned_data["email"],
            is_active=False,
            email_verified_at__isnull=True,
        ).first()
        if user:
            _send_verification(request, user)
        return redirect("signup_sent")
    return render(request, "resend_verification.html", {"form": form})