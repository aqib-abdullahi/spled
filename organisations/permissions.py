from .models import Membership

Role = Membership.Role

# Actions
VIEW_SITES = "view_sites"
LOG_EVIDENCE = "log_evidence"
APPROVE_ENTRIES = "approve_entries"
EDIT_SITES = "edit_sites"
AMEND_ENTRY = "amend_entry"
SIGN_OFF = "sign_off"
PUBLISH = "publish"
CREATE_SHARE_LINKS = "create_share_links"
MANAGE_TEAM = "manage_team"
MANAGE_ORGANISATION = "manage_organisation"  # settings and billing

ALL_ROLES = {r.value for r in Role}

# The roles matrix from the design, in one place.
PERMISSIONS = {
    VIEW_SITES: ALL_ROLES,
    LOG_EVIDENCE: {Role.ADMIN, Role.EDITOR, Role.FIELD, Role.CONTRACTOR},
    APPROVE_ENTRIES: {Role.ADMIN, Role.EDITOR},
    EDIT_SITES: {Role.ADMIN, Role.EDITOR},
    AMEND_ENTRY: {Role.ADMIN, Role.EDITOR},
    SIGN_OFF: {Role.ADMIN, Role.EDITOR, Role.OWNER},
    PUBLISH: {Role.ADMIN, Role.EDITOR},
    CREATE_SHARE_LINKS: {Role.ADMIN, Role.EDITOR, Role.OWNER},
    MANAGE_TEAM: {Role.ADMIN},
    MANAGE_ORGANISATION: {Role.ADMIN},
}

# Contractors may log evidence, but it waits for review before it counts.
NEEDS_REVIEW = {Role.CONTRACTOR}


def role_in(user, organisation):
    """The user's role in this organisation, or None if they are not a member."""
    if not user.is_authenticated or not user.is_active:
        return None
    return (
        Membership.objects.filter(user=user, organisation=organisation)
        .values_list("role", flat=True)
        .first()
    )


def can(user, action, organisation):
    allowed = PERMISSIONS[action]  # an unknown action raises KeyError on purpose
    role = role_in(user, organisation)
    return role is not None and role in allowed


def can_publish(user, site):
    org = site.organisation
    return can(user, PUBLISH, org) and org.is_verified


def needs_review(user, organisation):
    return role_in(user, organisation) in NEEDS_REVIEW