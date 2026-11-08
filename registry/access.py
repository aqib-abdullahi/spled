from organisations.models import Organisation

from .models import EvidenceEntry, Site


def sites_for(user, include_archived=False):
    """Only sites in organisations the user belongs to."""
    if not user.is_authenticated or not user.is_active:
        return Site.objects.none()
    qs = Site.objects.filter(organisation__memberships__user=user)
    if not include_archived:
        qs = qs.filter(archived_at__isnull=True)
    return qs


def evidence_for(user):
    return EvidenceEntry.objects.filter(site__in=sites_for(user, include_archived=True))


def public_sites():
    """What the public portal may show: published, not archived, verified owner."""
    return Site.objects.filter(
        is_public=True,
        archived_at__isnull=True,
        organisation__verification=Organisation.Verification.VERIFIED,
    )