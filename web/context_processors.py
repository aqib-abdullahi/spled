from organisations.permissions import APPROVE_ENTRIES, can
from registry.models import EvidenceEntry

from .context import get_current_membership


def review_nav(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    membership = get_current_membership(request)
    if not membership or not can(user, APPROVE_ENTRIES, membership.organisation):
        return {"nav_can_review": False}
    count = EvidenceEntry.objects.filter(
        site__organisation=membership.organisation,
        needs_review=True,
        review__isnull=True,
    ).count()
    return {"nav_can_review": True, "nav_pending_count": count}