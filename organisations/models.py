from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Organisation(models.Model):
    class Kind(models.TextChoices):
        GOVERNMENT = "government", "Government agency"
        PRIVATE = "private", "Developer or private owner"

    class Verification(models.TextChoices):
        PENDING = "pending", "Pending"
        VERIFIED = "verified", "Verified"
        MORE_INFO = "more_info", "More information requested"
        REJECTED = "rejected", "Rejected"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    verification = models.CharField(
        max_length=20, choices=Verification.choices, default=Verification.PENDING
    )
    public_name = models.CharField(
        max_length=200, blank=True, help_text="Name shown on the public portal."
    )

    # Evidence rules (Organisation settings screen)
    stale_after_days = models.PositiveSmallIntegerField(default=21)
    require_onsite_for_status_changes = models.BooleanField(default=True)
    publish_new_sites_automatically = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_verified(self):
        return self.verification == self.Verification.VERIFIED

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:70] or "organisation"
            slug, n = base, 2
            while Organisation.objects.filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Membership(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        EDITOR = "editor", "Editor"
        FIELD = "field", "Field"
        CONTRACTOR = "contractor", "Contractor"
        OWNER = "owner", "Owner"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organisation"], name="one_membership_per_org"
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.organisation} ({self.role})"