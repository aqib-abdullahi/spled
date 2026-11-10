from django.db.models import F, Max, Q
from django.shortcuts import get_object_or_404, render

from registry.access import COUNTED, public_sites
from registry.models import EvidenceEntry, Site


def _projects():
    return public_sites().select_related("organisation").annotate(
        last_verified=Max(
            "evidence__created_at",
            filter=Q(evidence__verified_on_site=True) & COUNTED,
        )
    )


def public_home(request):
    projects = _projects()
    evidence = EvidenceEntry.objects.filter(site__in=public_sites()).counted()
    return render(request, "public_home.html", {
        "recent": projects.order_by(
            F("last_verified").desc(nulls_last=True), "-updated_at"
        )[:6],
        "project_count": projects.count(),
        "evidence_count": evidence.count(),
        "verified_count": evidence.filter(verified_on_site=True).count(),
    })


def public_projects(request):
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    everything = _projects()
    qs = everything
    if status in Site.Status.values:
        qs = qs.filter(status=status)
    else:
        status = ""
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(owner_name__icontains=q)
            | Q(organisation__name__icontains=q)
            | Q(organisation__public_name__icontains=q)
        )
    counts = {}
    for site in everything:
        counts[site.status] = counts.get(site.status, 0) + 1
    chips = [{"key": "", "label": "All", "count": len(list(everything))}] + [
        {"key": k, "label": label, "count": counts.get(k, 0)}
        for k, label in Site.Status.choices
    ]
    return render(request, "public_projects.html", {
        "projects": qs.order_by(F("last_verified").desc(nulls_last=True), "name"),
        "chips": chips, "status": status, "q": q,
    })


def public_project(request, pk):
    site = get_object_or_404(_projects(), pk=pk)
    return render(request, "public_project.html", {
        "site": site,
        "org": site.organisation,
        "evidence": site.evidence.counted()
        .prefetch_related("photos", "amendments")
        .order_by("-created_at", "-id"),
    })