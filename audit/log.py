from .models import AuditEvent


def record(actor, organisation, action, target_id=None, target_label="", **detail):
    return AuditEvent.objects.create(
        organisation=organisation,
        actor=actor,
        actor_label=f"{actor.full_name} ({actor.email})",
        action=action,
        target_id=target_id,
        target_label=(target_label or "")[:200],
        detail=detail,
    )