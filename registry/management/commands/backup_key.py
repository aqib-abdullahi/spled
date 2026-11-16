from django.core.management.base import BaseCommand

from registry import crypto


class Command(BaseCommand):
    help = "Print a new random backup encryption key."

    def handle(self, *args, **options):
        self.stdout.write(crypto.generate_key())
        self.stderr.write(
            "Copy this into a password manager and into BACKUP_ENCRYPTION_KEY in .env.backup.\n"
            "If it is lost, every encrypted backup is permanently unreadable.\n"
            "Do not paste it into chats, tickets or terminal commands."
        )