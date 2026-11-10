import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
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

INVITE_DAYS = 7


class Invitation(models.Model):
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20, choices=Membership.Role.choices, default=Membership.Role.VIEWER
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "email"],
                condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="one_open_invite_per_email",
            )
        ]

    def __str__(self):
        return f"Invitation for {self.email} to {self.organisation}"

    @staticmethod
    def hash_token(raw):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def create_for(cls, organisation, email, role, invited_by):
        """Create an invitation. Returns (invitation, raw_token). The token is
        shown once and only its fingerprint is stored."""
        email = email.strip().lower()
        now = timezone.now()
        cls.objects.filter(
            organisation=organisation,
            email=email,
            accepted_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__lte=now,
        ).update(revoked_at=now)
        raw = secrets.token_urlsafe(32)
        invitation = cls.objects.create(
            organisation=organisation,
            email=email,
            role=role,
            invited_by=invited_by,
            token_hash=cls.hash_token(raw),
            expires_at=now + timedelta(days=INVITE_DAYS),
        )
        return invitation, raw

    @classmethod
    def lookup(cls, raw):
        return (
            cls.objects.select_related("organisation")
            .filter(token_hash=cls.hash_token(raw))
            .first()
        )

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def state(self):
        if self.accepted_at:
            return "accepted"
        if self.revoked_at:
            return "revoked"
        if self.is_expired:
            return "expired"
        return "pending"

    def accept(self, user):
        if self.state != "pending":
            raise ValueError("This invitation can no longer be used.")
        if user.email.lower() != self.email:
            raise ValueError("This invitation is for a different email address.")
        Membership.objects.get_or_create(
            user=user, organisation=self.organisation, defaults={"role": self.role}
        )
        self.accepted_at = timezone.now()
        self.save(update_fields=["accepted_at"])
