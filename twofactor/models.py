from django.conf import settings
from django.db import models


class TwoFactor(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="two_factor"
    )
    secret = models.CharField(max_length=64, editable=False)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    last_used_step = models.BigIntegerField(default=-1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Two-step verification for {self.user}"

    @property
    def is_active(self):
        return self.confirmed_at is not None


class BackupCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="backup_codes"
    )
    code_hash = models.CharField(max_length=64, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)