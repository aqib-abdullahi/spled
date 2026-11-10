from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_safe

from registry.access import public_sites, sites_for
from registry.models import EvidenceEntry, EvidencePhoto

VARIANTS = ("display", "thumb")  # the original is never served


def _may_view(user, photo):
    entry = photo.entry
    is_public = (
        EvidenceEntry.objects.counted()
        .filter(pk=entry.pk, site__in=public_sites())
        .exists()
    )
    if is_public:
        return True
    if user.is_authenticated:
        return sites_for(user, include_archived=True).filter(pk=entry.site_id).exists()
    return False


@require_safe
def photo_file(request, pk, variant):
    if variant not in VARIANTS:
        raise Http404
    photo = get_object_or_404(EvidencePhoto.objects.select_related("entry"), pk=pk)
    if not _may_view(request.user, photo):
        raise Http404
    field = getattr(photo, variant)
    try:
        with field.open("rb") as handle:
            data = handle.read()
    except (FileNotFoundError, ValueError):
        raise Http404
    response = HttpResponse(data, content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=300"
    response["Content-Disposition"] = "inline"
    return response
