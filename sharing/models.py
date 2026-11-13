import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from registry.models import Site

MAX_ACTIVE_PER_SITE = 20
EXPIRY_DAYS = (7, 30, 90)
MAX_FAILED = 10
LOCK_MINUTES = 15


class ShareLink(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="share_links")
    label = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    password_hash = models.CharField(max_length=255, blank=True, editable=False)
    include_photos = models.BooleanField(default=True)
    include_milestones = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0, editable=False)
    last_viewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    failed_attempts = models.PositiveSmallIntegerField(default=0, editable=False)
    locked_until = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.label} ({self.site})"

    @staticmethod
    def hash_token(raw):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def create_for(
        cls, site, label, created_by, days=30,
        include_photos=True, include_milestones=True, password="",
    ):
        """Returns (link, raw_token). The raw token is shown once and never stored."""
        raw = secrets.token_urlsafe(32)
        link = cls.objects.create(
            site=site,
            label=label.strip()[:100],
            created_by=created_by,
            token_hash=cls.hash_token(raw),
            password_hash=make_password(password) if password else "",
            include_photos=include_photos,
            include_milestones=include_milestones,
            expires_at=timezone.now() + timedelta(days=days),
        )
        return link, raw

    @classmethod
    def lookup(cls, raw):
        if not raw:
            return None
        return (
            cls.objects.select_related("site", "site__organisation")
            .filter(token_hash=cls.hash_token(raw))
            .first()
        )

    @property
    def has_password(self):
        return bool(self.password_hash)

    @property
    def state(self):
        if self.revoked_at:
            return "revoked"
        if timezone.now() >= self.expires_at:
            return "expired"
        if self.site.archived_at:
            return "unavailable"
        return "active"

    @property
    def is_active(self):
        return self.state == "active"

    @property
    def is_locked(self):
        return self.locked_until is not None and self.locked_until > timezone.now()

    def try_password(self, raw):
        """Returns "ok", "wrong" or "locked". Counts failures and locks the link."""
        with transaction.atomic():
            fresh = ShareLink.objects.select_for_update().get(pk=self.pk)
            now = timezone.now()
            if fresh.locked_until and fresh.locked_until > now:
                result = "locked"
            else:
                if fresh.locked_until:
                    fresh.locked_until = None
                    fresh.failed_attempts = 0
                if fresh.password_hash and check_password(raw or "", fresh.password_hash):
                    fresh.failed_attempts = 0
                    result = "ok"
                else:
                    fresh.failed_attempts += 1
                    if fresh.failed_attempts >= MAX_FAILED:
                        fresh.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                        fresh.failed_attempts = 0
                        result = "locked"
                    else:
                        result = "wrong"
            fresh.save(update_fields=["failed_attempts", "locked_until"])
        self.failed_attempts = fresh.failed_attempts
        self.locked_until = fresh.locked_until
        return result

    def record_view(self):
        ShareLink.objects.filter(pk=self.pk).update(
            view_count=F("view_count") + 1, last_viewed_at=timezone.now()
        )