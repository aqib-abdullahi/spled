from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import Point
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from organisations.permissions import (
    EDIT_SITES,
    LOG_EVIDENCE,
    PUBLISH,
    can,
    needs_review,
)
from registry.access import sites_for
from registry.models import EvidenceEntry, Site

from .context import get_current_membership
from .forms import EvidenceForm, SiteForm

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

class OnSiteRequired(Exception):
    pass


def _site_in_current_org(request, pk):
    membership = get_current_membership(request)
    if not membership:
        return None, None
    org = membership.organisation
    site = get_object_or_404(sites_for(request.user).filter(organisation=org), pk=pk)
    return org, site


@login_required
def site_detail(request, pk):
    org, site = _site_in_current_org(request, pk)
    if site is None:
        return redirect("overview")
    contractor = needs_review(request.user, org)
    return render(request, "site_detail.html", {
        "active": "sites",
        "org": org,
        "site": site,
        "evidence": list(
            site.evidence.select_related("author").order_by("-created_at", "-id")
        ),
        "chain_ok": not EvidenceEntry.verify_chain(site),
        "can_edit": can(request.user, EDIT_SITES, org),
        "can_log": can(request.user, LOG_EVIDENCE, org) and not contractor,
        "is_contractor": contractor,
        "can_publish_role": can(request.user, PUBLISH, org),
    })


@login_required
def evidence_new(request, pk):
    org, site = _site_in_current_org(request, pk)
    if site is None:
        return redirect("overview")
    if not can(request.user, LOG_EVIDENCE, org):
        raise PermissionDenied
    if needs_review(request.user, org):
        messages.info(
            request, "Contractor entries need a review step, which isn’t available yet."
        )
        return redirect("site_detail", pk=site.pk)

    form = EvidenceForm(request.POST or None, site=site)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        new_status = d["new_status"]
        point = (
            Point(d["longitude"], d["latitude"], srid=4326)
            if d["latitude"] is not None
            else None
        )
        try:
            with transaction.atomic():
                entry = EvidenceEntry.objects.create(
                    site=site,
                    author=request.user,
                    kind=EvidenceEntry.Kind.STATUS if new_status else d["kind"],
                    body=d["body"],
                    tags=d["tags"],
                    location=point,
                )
                if new_status:
                    if org.require_onsite_for_status_changes and not entry.verified_on_site:
                        raise OnSiteRequired
                    Site.objects.filter(pk=site.pk).update(
                        status=new_status, updated_at=timezone.now()
                    )
        except OnSiteRequired:
            form.add_error(
                "new_status",
                "Changing the status needs a location on site. "
                "Add your location, or leave the status as it is.",
            )
        else:
            messages.success(request, "Evidence added.")
            return redirect("site_detail", pk=site.pk)

    return render(request, "evidence_form.html", {
        "active": "sites", "form": form, "site": site, "org": org,
    })


@login_required
@require_POST
def site_publish(request, pk):
    org, site = _site_in_current_org(request, pk)
    if site is None:
        return redirect("overview")
    if not can(request.user, PUBLISH, org):
        raise PermissionDenied

    if site.is_public:
        site.is_public = False
        site.save(update_fields=["is_public", "updated_at"])
        messages.success(request, f"“{site.name}” is no longer public.")
    elif not org.is_verified:
        messages.error(
            request, "Your organisation must be verified before you can publish."
        )
    else:
        site.is_public = True
        try:
            site.clean()
        except ValidationError as e:
            messages.error(request, " ".join(sum(e.message_dict.values(), [])))
        else:
            site.save(update_fields=["is_public", "updated_at"])
            messages.success(request, f"“{site.name}” is now public.")
    return redirect("site_detail", pk=site.pk)