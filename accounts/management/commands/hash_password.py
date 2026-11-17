from getpass import getpass

from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Prompt for a password and print its hash, for ADMIN_PASSWORD_HASH."

    def handle(self, *args, **options):
        first = getpass("New admin password: ")
        second = getpass("Type it again: ")
        if first != second:
            raise CommandError("The two passwords differ.")
        try:
            validate_password(first)
        except ValidationError as exc:
            raise CommandError("Too weak: " + " ".join(exc.messages))
        self.stdout.write(make_password(first))
        self.stderr.write(
            "Put that line in ADMIN_PASSWORD_HASH. It is a hash, not your password, "
            "but a short password can still be guessed from it, so use a long one."
        )