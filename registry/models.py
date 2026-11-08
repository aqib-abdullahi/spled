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