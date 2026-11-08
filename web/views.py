from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from organisations.permissions import EDIT_SITES, can
from registry.access import sites_for
from registry.models import Site

from .context import get_current_membership
from .forms import SiteForm


def home(request):
    return redirect("overview" if request.user.is_authenticated else "signin")


@login_required
def overview(request):
    membership = get_current_membership(request)
    context = {"active": "overview", "membership": membership}

    if membership:
        org = membership.organisation
        base = sites_for(request.user).filter(organisation=org)

        counts = {key: 0 for key, _ in Site.Status.choices}
        for row in base.order_by().values("status").annotate(n=Count("id")):
            counts[row["status"]] = row["n"]

        cutoff = timezone.now() - timedelta(days=org.stale_after_days)
        sites = list(base.annotate(last_evidence=Max("evidence__created_at")).order_by("name"))
        attention = 0
        for site in sites:
            quiet_since = site.last_evidence or site.created_at
            site.needs_attention = (
                site.status in (Site.Status.DELAYED, Site.Status.STALLED)
                or quiet_since < cutoff
            )
            attention += site.needs_attention

        context.update(
            org=org,
            sites=sites,
            total=len(sites),
            attention_count=attention,
            stale_days=org.stale_after_days,
            status_counts=[
                {"key": key, "label": label, "count": counts[key]}
                for key, label in Site.Status.choices
            ],
        )

    return render(request, "overview.html", context)


@login_required
def sites_list(request):
    membership = get_current_membership(request)
    if not membership:
        return redirect("overview")
    org = membership.organisation
    in_org = sites_for(request.user).filter(organisation=org)

    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    qs = in_org
    if status in Site.Status.values:
        qs = qs.filter(status=status)
    else:
        status = ""
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(owner_name__icontains=q))

    counts = {
        r["status"]: r["n"]
        for r in in_org.order_by().values("status").annotate(n=Count("id"))
    }
    chips = [{"key": "", "label": "All", "count": sum(counts.values())}] + [
        {"key": k, "label": label, "count": counts.get(k, 0)}
        for k, label in Site.Status.choices
    ]

    return render(request, "sites.html", {
        "active": "sites",
        "membership": membership,
        "org": org,
        "sites": qs.annotate(last_evidence=Max("evidence__created_at")).order_by("name"),
        "chips": chips,
        "status": status,
        "q": q,
        "can_edit": can(request.user, EDIT_SITES, org),
    })


@login_required
def site_create(request):
    membership = get_current_membership(request)
    if not membership:
        return redirect("overview")
    org = membership.organisation
    if not can(request.user, EDIT_SITES, org):
        raise PermissionDenied

    form = SiteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        site = form.save(commit=False)
        site.organisation = org
        site.created_by = request.user
        site.save()
        messages.success(request, f"“{site.name}” was added.")
        return redirect("sites")
    return render(request, "site_form.html", {
        "active": "sites", "form": form, "title": "New site", "org": org,
    })


@login_required
def site_edit(request, pk):
    membership = get_current_membership(request)
    if not membership:
        return redirect("overview")
    org = membership.organisation
    site = get_object_or_404(sites_for(request.user).filter(organisation=org), pk=pk)
    if not can(request.user, EDIT_SITES, org):
        raise PermissionDenied

    form = SiteForm(request.POST or None, instance=site)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"“{site.name}” was saved.")
        return redirect("sites")
    return render(request, "site_form.html", {
        "active": "sites", "form": form, "title": "Edit site", "org": org, "site": site,
    })