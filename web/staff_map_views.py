from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from registry.access import sites_for
from registry.models import Site

from .context import get_current_membership

MAP_LIMIT = 2000


def _org_sites(request):
    """The current organisation's active sites, built on sites_for().
    Never public_sites(): staff see unpublished sites too."""
    membership = get_current_membership(request)
    if not membership:
        return None, [], False
    org = membership.organisation
    qs = sites_for(request.user).filter(organisation=org).order_by("name", "id")
    total = qs.count()
    return org, list(qs[:MAP_LIMIT]), total > MAP_LIMIT


@login_required
def staff_map(request):
    membership = get_current_membership(request)
    org, sites, truncated = _org_sites(request)
    counts = {key: 0 for key, _ in Site.Status.choices}
    for site in sites:
        counts[site.status] += 1
    return render(request, "staff_map.html", {
        "active": "map",
        "membership": membership,
        "org": org,
        "sites": sites,
        "truncated": truncated,
        "map_limit": MAP_LIMIT,
        "status_counts": [
            {"key": key, "label": label, "count": counts[key]}
            for key, label in Site.Status.choices
        ],
    })


def staff_map_data(request):
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in required."}, status=401)
    _org, sites, _truncated = _org_sites(request)
    features = []
    for site in sites:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [site.location.x, site.location.y],
            },
            "properties": {
                "id": site.pk,
                "name": site.name,
                "status": site.status,
                "status_label": site.get_status_display(),
                "progress": site.progress,
                "kind": site.get_kind_display(),
                "is_public": site.is_public,
                "url": reverse("site_detail", args=[site.pk]),
            },
        })
    response = JsonResponse({"type": "FeatureCollection", "features": features})
    # Private data: never let a shared cache keep it.
    response["Cache-Control"] = "private, no-store"
    return response