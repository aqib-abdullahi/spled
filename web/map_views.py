from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from registry.access import public_sites

MAP_LIMIT = 2000


def _projects():
    return list(
        public_sites().select_related("organisation").order_by("name", "id")[:MAP_LIMIT]
    )


def public_map(request):
    return render(request, "public_map.html", {"projects": _projects()})


def public_map_data(request):
    features = []
    for site in _projects():
        org = site.organisation
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
                "organisation": org.public_name or org.name,
                "url": reverse("project", args=[site.pk]),
            },
        })
    response = JsonResponse({"type": "FeatureCollection", "features": features})
    response["Cache-Control"] = "public, max-age=60"
    return response