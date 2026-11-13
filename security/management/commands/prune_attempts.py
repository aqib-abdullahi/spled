from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from security.models import Attempt


class Command(BaseCommand):
    help = "Delete rate-limit records older than a day."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=1)
        removed, _ = Attempt.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(f"Removed {removed} old attempt record(s).")