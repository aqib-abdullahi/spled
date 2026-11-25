from organisations.permissions import (
    APPROVE_ENTRIES,
    CREATE_SHARE_LINKS,
    EXPORT_REPORTS,
    MANAGE_ORGANISATION,
    MANAGE_TEAM,
    can,
)
from registry.models import EvidenceEntry

from .context import get_current_membership


def review_nav(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    membership = get_current_membership(request)
    if not membership:
        return {}
    org = membership.organisation
    result = {
        "nav_can_review": can(user, APPROVE_ENTRIES, org),
        "nav_can_audit": can(user, MANAGE_ORGANISATION, org),
        "nav_can_team": can(user, MANAGE_TEAM, org),
        "nav_can_export": can(user, EXPORT_REPORTS, org),
        "nav_can_share": can(user, CREATE_SHARE_LINKS, org),
        "nav_org_name": org.name,
    }
    if result["nav_can_review"]:
        result["nav_pending_count"] = EvidenceEntry.objects.filter(
            site__organisation=org, needs_review=True, review__isnull=True
        ).count()
    return result