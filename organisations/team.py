from django.db import transaction

from .models import Membership, Organisation

ADMIN = Membership.Role.ADMIN


class LastAdminError(Exception):
    pass


def _lock_and_check(membership, leaving_admin):
    # Lock the organisation row so two admins can't remove each other at once.
    Organisation.objects.select_for_update().get(pk=membership.organisation_id)
    membership.refresh_from_db()
    if membership.role == ADMIN and leaving_admin:
        others = (
            Membership.objects.filter(
                organisation_id=membership.organisation_id, role=ADMIN
            )
            .exclude(pk=membership.pk)
            .exists()
        )
        if not others:
            raise LastAdminError("An organisation needs at least one admin.")


def change_role(membership, new_role):
    """Change a role. Returns the old role."""
    if new_role not in Membership.Role.values:
        raise ValueError("Unknown role.")
    with transaction.atomic():
        _lock_and_check(membership, leaving_admin=new_role != ADMIN)
        old = membership.role
        membership.role = new_role
        membership.save(update_fields=["role"])
        return old


def remove_member(membership):
    with transaction.atomic():
        _lock_and_check(membership, leaving_admin=True)
        membership.delete()