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

from django.core.files.base import ContentFile
from organisations.models import Organisation

from .photos import check_photo_file, photo_upload_path, private_storage


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
    progress_from_milestones = models.BooleanField(default=False)
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

    @property
    def area_hectares(self):
        """Area of the drawn boundary in hectares, or None."""
        if not self.boundary:
            return None
        from .geo import area_hectares

        return area_hectares(self.boundary)

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
    def counted(self):
        # Entries that count: no review needed, or approved.
        return self.filter(
            models.Q(needs_review=False) | models.Q(review__decision="approved")
        )

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

    needs_review = models.BooleanField(default=False, editable=False)
    photo_hashes = ArrayField(
        models.CharField(max_length=64), default=list, blank=True, editable=False
    )
    previous_hash = models.CharField(max_length=64, blank=True, editable=False)
    content_hash = models.CharField(max_length=64, editable=False)

    objects = EvidenceQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "evidence entries"

    def __str__(self):
        return f"{self.get_kind_display()} on {self.site} ({self.created_at:%d %b %Y})"

    @property
    def review_state(self):
        if not self.needs_review:
            return "not_required"
        review = getattr(self, "review", None)
        return review.decision if review else "pending"

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
        if self.needs_review:
            payload["needs_review"] = True
        if self.photo_hashes:
            payload["photos"] = list(self.photo_hashes)
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
            if entry.photo_hashes:
                stored = sorted(entry.photos.values_list("sha256", flat=True))
                if stored != sorted(entry.photo_hashes):
                    problems.append((entry.id, "photos changed"))
            previous = entry.content_hash
        return problems

    @classmethod
    def verify_files(cls, site):
        """Re-read every photo file and compare it with its stored fingerprint."""
        problems = []
        for entry in cls.objects.filter(site=site).prefetch_related("photos"):
            for photo in entry.photos.all():
                problem = check_photo_file(photo)
                if problem:
                    problems.append((entry.id, problem))
        return problems

class EvidenceReview(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    entry = models.OneToOneField(
        EvidenceEntry, on_delete=models.PROTECT, related_name="review"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    decision = models.CharField(max_length=20, choices=Decision.choices)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_decision_display()}: {self.entry}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("A review decision cannot be changed.")
        if not self.entry.needs_review:
            raise ValueError("This entry does not need a review.")
        if self.entry.author_id == self.reviewer_id:
            raise ValueError("You cannot review your own entry.")
        if self.decision == self.Decision.REJECTED and not self.comment.strip():
            raise ValueError("A rejection needs a reason.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("A review decision cannot be deleted.")


class PhotoQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Photos cannot be changed.")

    def bulk_update(self, *args, **kwargs):
        raise PermissionError("Photos cannot be changed.")

    def delete(self):
        raise PermissionError("Photos cannot be deleted.")


class EvidencePhoto(models.Model):
    entry = models.ForeignKey(
        EvidenceEntry, on_delete=models.PROTECT, related_name="photos"
    )
    original = models.FileField(
        storage=private_storage, upload_to=photo_upload_path, max_length=200
    )
    display = models.FileField(
        storage=private_storage, upload_to=photo_upload_path, max_length=200
    )
    thumb = models.FileField(
        storage=private_storage, upload_to=photo_upload_path, max_length=200
    )
    sha256 = models.CharField(max_length=64, editable=False)
    width = models.PositiveIntegerField(editable=False)
    height = models.PositiveIntegerField(editable=False)
    size_bytes = models.PositiveIntegerField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PhotoQuerySet.as_manager()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Photo {self.pk} on entry {self.entry_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Photos cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Photos cannot be deleted.")

    def remove_files(self):
        for field in (self.original, self.display, self.thumb):
            if field and field.name:
                field.storage.delete(field.name)

    @classmethod
    def create_from(cls, entry, processed):
        photo = cls(
            entry=entry,
            sha256=processed.sha256,
            width=processed.width,
            height=processed.height,
            size_bytes=len(processed.original),
        )
        try:
            photo.original.save(
                f"original.{processed.ext}", ContentFile(processed.original), save=False
            )
            photo.display.save("display.jpg", ContentFile(processed.display), save=False)
            photo.thumb.save("thumb.jpg", ContentFile(processed.thumb), save=False)
            photo.save()
        except Exception:
            photo.remove_files()
            raise
        return photo


class Milestone(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=120)
    due_date = models.DateField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.title} ({self.site})"

    @property
    def is_done(self):
        return self.completed_at is not None
