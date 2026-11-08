from organisations.models import Membership


def get_current_membership(request):
    """The membership the user is currently acting under, or None."""
    user = request.user
    if not user.is_authenticated:
        return None
    memberships = list(
        Membership.objects.filter(user=user)
        .select_related("organisation")
        .order_by("organisation__name")
    )
    chosen = request.session.get("org_id")
    for m in memberships:
        if m.organisation_id == chosen:
            return m
    return memberships[0] if memberships else None