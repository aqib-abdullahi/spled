import os

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import identify_hasher
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone


def clean(value):
    return str(value or "").strip()


class Command(BaseCommand):
    help = (
        "Create the first admin account from ADMIN_EMAIL, ADMIN_NAME and ADMIN_PASSWORD_HASH, "
        "once. Never changes an account that already exists."
    )

    def handle(self, *args, **options):
        email = clean(os.environ.get("ADMIN_EMAIL")).lower()
        if not email:
            self.stdout.write("ADMIN_EMAIL is not set: no admin account created.")
            return
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError("ADMIN_EMAIL is not a valid email address.")

        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            self.stdout.write("An account for that email already exists: left unchanged.")
            return

        name = clean(os.environ.get("ADMIN_NAME")) or "Administrator"
        password_hash = clean(os.environ.get("ADMIN_PASSWORD_HASH"))
        password = str(os.environ.get("ADMIN_PASSWORD", "")).strip("\r\n")

        # Check everything before creating anything.
        if password_hash:
            try:
                identify_hasher(password_hash)
            except ValueError:
                raise CommandError(
                    "ADMIN_PASSWORD_HASH is not a valid Django password hash. "
                    "Make one with: python manage.py hash_password"
                )
        elif password:
            try:
                validate_password(password, user=User(email=email, full_name=name))
            except ValidationError as exc:
                raise CommandError("ADMIN_PASSWORD is too weak: " + " ".join(exc.messages))
        else:
            raise CommandError(
                "Set ADMIN_PASSWORD_HASH (make one with: python manage.py hash_password), "
                "or ADMIN_PASSWORD."
            )

        with transaction.atomic():
            user = User.objects.create_superuser(
                email, None if password_hash else password,
                full_name=name, email_verified_at=timezone.now(),
            )
            if password_hash:
                user.password = password_hash
                user.save(update_fields=["password"])

        self.stdout.write(self.style.SUCCESS(
            f"Created admin account {email}. Sign in at /signin/, then turn on "
            "two-step verification under Security."
        ))