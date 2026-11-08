import hashlib
import json
import math
from datetime import timezone as dt_timezone

from django.contrib.postgres.fields import ArrayField
from django.db import transaction

from django.conf import settings
from django.contrib.gis.db import models as gis
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from organisations.models import Organisation


class Site(models.Model):
    class Kind(models.TextChoices):
        ROAD = "road", "Road"
        BUILDING = "building", "Building"
        POWER = "power", "Power"
        AGRICULTURE = "agriculture", "Agriculture"
        INFRASTRUCTURE = "infrastructure", "Infrastructure"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In progress"
        DELAYED = "delayed", "Delayed"
        STALLED = "stalled", "Stalled"
        COMPLETE = "complete", "Complete"

    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="sites"
    )
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PLANNED
    )
    owner_name = models.CharField(max_length=200, blank=True)
    target_date = models.DateField(null=True, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    description = models.TextField(blank=True)

    location = gis.PointField(srid=4326)
    boundary = gis.PolygonField(srid=4326, null=True, blank=True)

    is_public = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(progress__lte=100), name="progress_max_100"
            )
        ]

    def __str__(self):
        return self.name

    @property
    def is_archived(self):
        return self.archived_at is not None

    def archive(self):
        self.archived_at = timezone.now()
        self.is_public = False
        self.save(update_fields=["archived_at", "is_public", "updated_at"])

    def clean(self):
        if self.is_public and not self.organisation.is_verified:
            raise ValidationError(
                {"is_public": "Only verified organisations can publish sites."}
            )
        if self.boundary and not self.boundary.valid:
            raise ValidationError({"boundary": "The boundary shape is not valid."})

VERIFY_RADIUS_M = 100


def distance_m(a, b):
    """Great-circle distance in metres between two lon/lat points."""
    r = 6371008.8
    lon1, lat1, lon2, lat2 = map(math.radians, (a.x, a.y, b.x, b.y))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(h))


class EvidenceQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Evidence cannot be changed.")

    def bulk_update(self, *args, **kwargs):
        raise PermissionError("Evidence cannot be changed.")

    def delete(self):
        raise PermissionError("Evidence cannot be deleted.")


class EvidenceEntry(models.Model):
    class Kind(models.TextChoices):
        NOTE = "note", "Note"
        PHOTO = "photo", "Photo"
        CHECK_IN = "check_in", "Field check-in"
        STATUS = "status", "Status update"

    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="evidence")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    body = models.TextField()
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    captured_at = models.DateTimeField(
        default=timezone.now, help_text="Time reported by the device."
    )
    created_at = models.DateTimeField(editable=False)  # server time, authoritative

    location = gis.PointField(srid=4326, null=True, blank=True)
    distance_to_site_m = models.FloatField(null=True, blank=True, editable=False)
    verified_on_site = models.BooleanField(default=False, editable=False)

    amends = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="amendments",
    )
    amendment_reason = models.CharField(max_length=200, blank=True)

    previous_hash = models.CharField(max_length=64, blank=True, editable=False)
    content_hash = models.CharField(max_length=64, editable=False)

    objects = EvidenceQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "evidence entries"

    def __str__(self):
        return f"{self.get_kind_display()} on {self.site} ({self.created_at:%d %b %Y})"

    def _compute_verification(self):
        if self.location is None:
            self.distance_to_site_m = None
            self.verified_on_site = False
            return
        self.distance_to_site_m = distance_m(self.location, self.site.location)
        inside = self.site.boundary is not None and self.site.boundary.contains(
            self.location
        )
        self.verified_on_site = inside or self.distance_to_site_m <= VERIFY_RADIUS_M

    def compute_hash(self):
        payload = {
            "site": self.site_id,
            "author": self.author_id,
            "kind": self.kind,
            "body": self.body,
            "tags": list(self.tags),
            "captured_at": self.captured_at.astimezone(dt_timezone.utc).isoformat(),
            "created_at": self.created_at.astimezone(dt_timezone.utc).isoformat(),
            "location": self.location.wkt if self.location else None,
            "distance": None
            if self.distance_to_site_m is None
            else round(self.distance_to_site_m, 3),
            "verified": self.verified_on_site,
            "amends": self.amends_id,
            "reason": self.amendment_reason,
            "previous": self.previous_hash,
        }
        text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError(
                "Evidence cannot be changed. Add an amendment instead."
            )
        if self.amends_id:
            if not self.amendment_reason:
                raise ValueError("An amendment needs a reason.")
            if self.amends.site_id != self.site_id:
                raise ValueError("An amendment must be on the same site.")
        with transaction.atomic():
            # Lock the site so two entries can't extend the chain at once.
            Site.objects.select_for_update().get(pk=self.site_id)
            last = (
                EvidenceEntry.objects.filter(site_id=self.site_id)
                .order_by("-id")
                .first()
            )
            self.previous_hash = last.content_hash if last else ""
            self.created_at = timezone.now()
            self._compute_verification()
            self.content_hash = self.compute_hash()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Evidence cannot be deleted.")

    @classmethod
    def verify_chain(cls, site):
        """Return a list of (entry id, problem). Empty means the chain is intact."""
        problems = []
        previous = ""
        for entry in cls.objects.filter(site=site).order_by("id"):
            if entry.previous_hash != previous:
                problems.append((entry.id, "chain broken"))
            if entry.content_hash != entry.compute_hash():
                problems.append((entry.id, "content changed"))
            previous = entry.content_hash
        return problems