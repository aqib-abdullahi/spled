from django.db import models
from django.utils import timezone


class Attempt(models.Model):
    """One counted event for rate limiting. The key is stored only as a hash."""

    scope = models.CharField(max_length=40)
    key_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(
                fields=["scope", "key_hash", "created_at"], name="attempt_lookup"
            )
        ]

    def __str__(self):
        return f"{self.scope} at {self.created_at:%Y-%m-%d %H:%M}"