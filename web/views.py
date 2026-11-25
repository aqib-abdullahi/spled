from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import Point
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.log import record
from audit.models import AuditEvent
from organisations.permissions import (
    AMEND_ENTRY,
    APPROVE_ENTRIES,
    EDIT_SITES,
    LOG_EVIDENCE,
    MANAGE_ORGANISATION,
    PUBLISH,
    can,
    needs_review,
)
from registry.access import COUNTED, sites_for
from registry.models import (
    MAX_FIX_ACCURACY_M,
    SOURCE_DEVICE,
    EvidenceEntry,
    EvidencePhoto,
    EvidenceReview,
    Site,
)

from .context import get_current_membership
from .forms import AmendForm, EvidenceForm, SiteForm


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
        sites = list(
            base.annotate(
                last_evidence=Max("evidence__created_at", filter=COUNTED)
            ).order_by("name")
        )
        now = timezone.now()
        attention = 0
        flagged = []
        for site in sites:
            quiet_since = site.last_evidence or site.created_at
            # Finished work is expected to go quiet.
            quiet = quiet_since < cutoff and site.status != Site.Status.COMPLETE
            site.needs_attention = (
                site.status in (Site.Status.DELAYED, Site.Status.STALLED) or quiet
            )
            attention += site.needs_attention
            if not site.needs_attention:
                continue
            reasons = []
            rank = 2
            if site.status == Site.Status.STALLED:
                rank = 0
                reasons.append("Stalled")
            elif site.status == Site.Status.DELAYED:
                rank = 1
                reasons.append("Delayed")
            if quiet:
                days = (now - quiet_since).days
                unit = "day" if days == 1 else "days"
                if site.last_evidence:
                    reasons.append(f"No evidence for {days} {unit}")
                else:
                    reasons.append(f"No evidence yet, added {days} {unit} ago")
            site.attention_reason = " · ".join(reasons)
            flagged.append((rank, quiet_since, site.pk, site))
        flagged.sort(key=lambda row: row[:3])
        attention_sites = [row[3] for row in flagged]

        context.update(
            org=org,
            sites=sites,
            total=len(sites),
            has_any_evidence=any(s.last_evidence for s in sites),
            can_add_site=can(request.user, EDIT_SITES, org),
            attention_sites=attention_sites[:5],
            attention_more=max(0, len(attention_sites) - 5),
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
        "sites": qs.annotate(
            last_evidence=Max("evidence__created_at", filter=COUNTED)
        ).order_by("name"),
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
        auto = org.is_verified and org.publish_new_sites_automatically
        site.is_public = auto
        with transaction.atomic():
            site.save()
            record(
                request.user, org, AuditEvent.Action.SITE_CREATED, site.pk, site.name,
                auto_published=auto,
            )
        messages.success(
            request,
            f"“{site.name}” was added and published." if auto else f"“{site.name}” was added.",
        )
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
        changed = [str(form[n].label) for n in form.changed_data]
        with transaction.atomic():
            form.save()
            if changed:
                record(
                    request.user, org, AuditEvent.Action.SITE_EDITED,
                    site.pk, site.name, fields=changed,
                )
        if changed:
            messages.success(request, f"“{site.name}” was saved.")
        else:
            messages.info(request, "Nothing changed.")
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
    return render(request, "site_detail.html", {
        "active": "sites",
        "org": org,
        "site": site,
        "evidence": list(
            site.evidence.select_related("author", "review", "review__reviewer")
            .prefetch_related("photos", "amendments")
            .order_by("-created_at", "-id")
        ),
        "chain_ok": not EvidenceEntry.verify_chain(site),
        "can_edit": can(request.user, EDIT_SITES, org),
        "can_log": can(request.user, LOG_EVIDENCE, org),
        "is_contractor": needs_review(request.user, org),
        "can_publish_role": can(request.user, PUBLISH, org),
        "can_amend": can(request.user, AMEND_ENTRY, org),
    })


@login_required
def evidence_new(request, pk):
    org, site = _site_in_current_org(request, pk)
    if site is None:
        return redirect("overview")
    if not can(request.user, LOG_EVIDENCE, org):
        raise PermissionDenied
    contractor = needs_review(request.user, org)

    form = EvidenceForm(
        request.POST or None, request.FILES or None, site=site, allow_status=not contractor
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        new_status = d.get("new_status", "")
        photos = d["photos"]
        point = (
            Point(d["longitude"], d["latitude"], srid=4326)
            if d["latitude"] is not None
            else None
        )
        try:
            with transaction.atomic():
                entry = EvidenceEntry(
                    site=site,
                    author=request.user,
                    kind=EvidenceEntry.Kind.STATUS if new_status else d["kind"],
                    body=d["body"],
                    tags=d["tags"],
                    location=point,
                    location_source=SOURCE_DEVICE if point else "",
                    location_accuracy_m=d["accuracy"] if point else None,
                    needs_review=contractor,
                    photo_hashes=[p.sha256 for p in photos],
                )
                entry.fix_age_s = d["fix_age"] if point else None
                entry.save()
                if new_status:
                    if org.require_onsite_for_status_changes and not entry.verified_on_site:
                        raise OnSiteRequired
                    Site.objects.filter(pk=site.pk).update(
                        status=new_status, updated_at=timezone.now()
                    )
                saved = []
                try:
                    for processed in photos:
                        saved.append(EvidencePhoto.create_from(entry, processed))
                except Exception:
                    for done in saved:
                        done.remove_files()
                    raise
        except OnSiteRequired:
            form.add_error(
                "new_status",
                "Changing the status needs a location on site. "
                "Add your location, or leave the status as it is.",
            )
        else:
            messages.success(
                request, "Submitted for review." if contractor else "Evidence added."
            )
            return redirect("site_detail", pk=site.pk)

    return render(request, "evidence_form.html", {
        "active": "sites", "form": form, "site": site, "org": org,
        "allow_status": not contractor, "is_contractor": contractor,
        "max_accuracy": MAX_FIX_ACCURACY_M,
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
        with transaction.atomic():
            site.save(update_fields=["is_public", "updated_at"])
            record(request.user, org, AuditEvent.Action.SITE_UNPUBLISHED, site.pk, site.name)
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
            with transaction.atomic():
                site.save(update_fields=["is_public", "updated_at"])
                record(request.user, org, AuditEvent.Action.SITE_PUBLISHED, site.pk, site.name)
            messages.success(request, f"“{site.name}” is now public.")
    return redirect("site_detail", pk=site.pk)


@login_required
def review_queue(request):
    membership = get_current_membership(request)
    if not membership:
        return redirect("overview")
    org = membership.organisation
    if not can(request.user, APPROVE_ENTRIES, org):
        raise PermissionDenied

    pending = (
        EvidenceEntry.objects.filter(
            site__organisation=org, needs_review=True, review__isnull=True
        )
        .select_related("site", "author")
        .prefetch_related("photos")
        .order_by("created_at", "id")
    )
    recent = (
        EvidenceReview.objects.filter(entry__site__organisation=org)
        .select_related("entry__site", "entry__author", "reviewer")
        .order_by("-created_at")[:10]
    )
    return render(request, "review.html", {
        "active": "review", "org": org, "pending": pending, "recent": recent,
    })


@login_required
@require_POST
def review_decide(request, pk):
    membership = get_current_membership(request)
    if not membership:
        return redirect("overview")
    org = membership.organisation
    if not can(request.user, APPROVE_ENTRIES, org):
        raise PermissionDenied

    entry = get_object_or_404(
        EvidenceEntry, pk=pk, site__organisation=org, needs_review=True
    )
    if hasattr(entry, "review"):
        messages.info(request, "That entry has already been reviewed.")
        return redirect("review")
    if entry.author_id == request.user.id:
        raise PermissionDenied

    decision = request.POST.get("decision", "")
    comment = request.POST.get("comment", "").strip()
    if decision not in EvidenceReview.Decision.values:
        messages.error(request, "Choose approve or reject.")
        return redirect("review")
    if decision == EvidenceReview.Decision.REJECTED and len(comment) < 3:
        messages.error(request, "Say why you are rejecting it, so the contractor knows.")
        return redirect("review")

    try:
        with transaction.atomic():
            EvidenceReview.objects.create(
                entry=entry, reviewer=request.user, decision=decision, comment=comment
            )
            record(
                request.user, org,
                AuditEvent.Action.REVIEW_APPROVED
                if decision == "approved"
                else AuditEvent.Action.REVIEW_REJECTED,
                entry.site_id, entry.site.name, entry_id=entry.pk, comment=comment,
            )
    except IntegrityError:
        messages.info(request, "That entry has already been reviewed.")
    else:
        messages.success(
            request,
            "Approved. It now counts." if decision == "approved" else "Rejected.",
        )
    return redirect("review")

@login_required
def evidence_amend(request, pk):
    membership = get_current_membership(request)
    if not membership:
        return redirect("overview")
    org = membership.organisation
    if not can(request.user, AMEND_ENTRY, org):
        raise PermissionDenied
    entry = get_object_or_404(
        EvidenceEntry.objects.counted().select_related("site"),
        pk=pk,
        site__organisation=org,
        site__archived_at__isnull=True,
    )

    form = AmendForm(request.POST or None, initial={"body": entry.body})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if d["body"].strip() == entry.body.strip():
            form.add_error("body", "Change the text, or cancel.")
        else:
            with transaction.atomic():
                fix = EvidenceEntry.objects.create(
                    site=entry.site,
                    author=request.user,
                    kind=EvidenceEntry.Kind.NOTE,
                    body=d["body"],
                    amends=entry,
                    amendment_reason=d["reason"],
                )
                record(
                    request.user, org, AuditEvent.Action.EVIDENCE_AMENDED,
                    entry.site_id, entry.site.name,
                    entry_id=entry.pk, correction_id=fix.pk, reason=d["reason"],
                )
            messages.success(
                request, "Correction added. The original stays on the record."
            )
            return redirect("site_detail", pk=entry.site_id)

    return render(request, "amend_form.html", {
        "active": "sites", "form": form, "entry": entry, "site": entry.site, "org": org,
    })


AUDIT_GROUPS = {
    "sites": ["site.created", "site.edited"],
    "publishing": ["site.published", "site.unpublished"],
    "review": ["review.approved", "review.rejected"],
    "corrections": ["evidence.amended"],
    "settings": ["org.settings_changed"],
    "exports": ["report.exported"],
    "milestones": [
        "milestone.added", "milestone.completed", "milestone.reopened",
        "milestone.edited", "milestone.deleted",
    ],
    "team": [
        "member.invited", "invite.revoked", "member.joined",
        "member.role_changed", "member.removed",
    ],
}
AUDIT_CHIPS = [
    ("", "All"), ("sites", "Sites"), ("publishing", "Publishing"),
    ("review", "Review"), ("corrections", "Corrections"), ("team", "Team"), ("milestones", "Milestones"), ("settings", "Settings"), ("exports", "Exports"),
]


@login_required
def audit_log(request):
    membership = get_current_membership(request)
    if not membership:
        return redirect("overview")
    org = membership.organisation
    if not can(request.user, MANAGE_ORGANISATION, org):
        raise PermissionDenied

    group = request.GET.get("group", "")
    qs = AuditEvent.objects.filter(organisation=org)
    if group in AUDIT_GROUPS:
        qs = qs.filter(action__in=AUDIT_GROUPS[group])
    else:
        group = ""
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "audit.html", {
        "active": "audit", "org": org, "page": page, "group": group,
        "chips": [{"key": k, "label": label} for k, label in AUDIT_CHIPS],
    })
