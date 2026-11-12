from django.conf import settings
from django.db import models

from organisations.models import Organisation


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise PermissionError("Audit events cannot be changed.")

    def bulk_update(self, *args, **kwargs):
        raise PermissionError("Audit events cannot be changed.")

    def delete(self):
        raise PermissionError("Audit events cannot be deleted.")


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        SITE_CREATED = "site.created", "Site created"
        SITE_EDITED = "site.edited", "Site edited"
        SITE_PUBLISHED = "site.published", "Site published"
        SITE_UNPUBLISHED = "site.unpublished", "Site unpublished"
        REVIEW_APPROVED = "review.approved", "Entry approved"
        REVIEW_REJECTED = "review.rejected", "Entry rejected"
        EVIDENCE_AMENDED = "evidence.amended", "Entry amended"
        MEMBER_INVITED = "member.invited", "Person invited"
        INVITE_REVOKED = "invite.revoked", "Invitation revoked"
        MEMBER_JOINED = "member.joined", "Person joined"
        MEMBER_ROLE_CHANGED = "member.role_changed", "Role changed"
        MEMBER_REMOVED = "member.removed", "Person removed"
        MILESTONE_ADDED = "milestone.added", "Milestone added"
        MILESTONE_COMPLETED = "milestone.completed", "Milestone completed"
        MILESTONE_REOPENED = "milestone.reopened", "Milestone reopened"
        MILESTONE_EDITED = "milestone.edited", "Milestone edited"
        MILESTONE_DELETED = "milestone.deleted", "Milestone deleted"
        ORG_SETTINGS_CHANGED = "org.settings_changed", "Settings changed"
        REPORT_EXPORTED = "report.exported", "Report exported"

    organisation = models.ForeignKey(
        Organisation, on_delete=models.PROTECT, related_name="audit_events"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    actor_label = models.CharField(max_length=300)
    action = models.CharField(max_length=40, choices=Action.choices)
    target_id = models.PositiveIntegerField(null=True, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organisation", "-created_at"])]

    def __str__(self):
        return f"{self.get_action_display()}: {self.target_label}"

    @property
    def summary(self):
        d = self.detail or {}
        if self.action in (
            self.Action.SITE_EDITED,
            self.Action.ORG_SETTINGS_CHANGED,
        ) and d.get("fields"):
            return "Changed: " + ", ".join(d["fields"])
        if self.action == self.Action.REVIEW_REJECTED and d.get("comment"):
            return d["comment"]
        if self.action == self.Action.EVIDENCE_AMENDED and d.get("reason"):
            return "Reason: " + d["reason"]
        if self.action == self.Action.MEMBER_INVITED:
            return f"{d.get('email', '')} as {d.get('role', '')}"
        if self.action == self.Action.MEMBER_ROLE_CHANGED:
            return f"{d.get('email', '')}: {d.get('from', '')} to {d.get('to', '')}"
        if self.action == self.Action.MEMBER_REMOVED:
            return f"{d.get('email', '')} ({d.get('role', '')})"
        if self.action == self.Action.INVITE_REVOKED:
            return d.get("email", "")
        if self.action == self.Action.MEMBER_JOINED:
            return f"Joined as {d.get('role', '')}"
        if self.action == self.Action.SITE_CREATED and d.get("auto_published"):
            return "Published automatically"
        if self.action == self.Action.REPORT_EXPORTED:
            if d.get("kind") == "portfolio_csv":
                return f"CSV with {d.get('rows', 0)} site(s)"
            return f"Markdown report with {d.get('entries', 0)} entries"
        return ""

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError("Audit events cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit events cannot be deleted.")