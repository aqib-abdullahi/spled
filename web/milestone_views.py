from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.log import record
from audit.models import AuditEvent
from organisations.permissions import EDIT_SITES, can
from registry.access import sites_for
from registry.milestones import MAX_MILESTONES, recompute_progress
from registry.models import Milestone, Site

from .context import get_current_membership


class MilestoneForm(forms.Form):
    title = forms.CharField(max_length=120)
    due_date = forms.DateField(required=False)


def _load(request, pk, edit):
    membership = get_current_membership(request)
    if not membership:
        return None, None
    org = membership.organisation
    site = get_object_or_404(sites_for(request.user).filter(organisation=org), pk=pk)
    if edit and not can(request.user, EDIT_SITES, org):
        raise PermissionDenied
    return org, site


def _locked(site):
    # Lock the site row so two people can't reorder or tick at the same moment.
    return Site.objects.select_for_update().get(pk=site.pk)


def _label(site, milestone):
    return f"{site.name}: {milestone.title}"


@login_required
def milestones_page(request, pk):
    org, site = _load(request, pk, edit=False)
    if site is None:
        return redirect("overview")
    milestones = list(site.milestones.all())
    return render(request, "milestones.html", {
        "active": "sites",
        "org": org,
        "site": site,
        "milestones": milestones,
        "done": sum(1 for m in milestones if m.is_done),
        "total": len(milestones),
        "can_edit": can(request.user, EDIT_SITES, org),
        "max_milestones": MAX_MILESTONES,
    })


@login_required
@require_POST
def milestone_add(request, pk):
    org, site = _load(request, pk, edit=True)
    if site is None:
        return redirect("overview")
    form = MilestoneForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, "Give the milestone a title (up to 120 characters) and a valid date."
        )
        return redirect("milestones", pk=site.pk)
    with transaction.atomic():
        locked = _locked(site)
        if locked.milestones.count() >= MAX_MILESTONES:
            messages.error(request, f"A site can have at most {MAX_MILESTONES} milestones.")
            return redirect("milestones", pk=site.pk)
        last = locked.milestones.order_by("-position").first()
        m = Milestone.objects.create(
            site=locked,
            title=form.cleaned_data["title"],
            due_date=form.cleaned_data["due_date"],
            position=(last.position + 1) if last else 0,
        )
        record(
            request.user, org, AuditEvent.Action.MILESTONE_ADDED,
            site.pk, _label(site, m), milestone_id=m.pk,
        )
        recompute_progress(locked)
    messages.success(request, "Milestone added.")
    return redirect("milestones", pk=site.pk)


@login_required
@require_POST
def milestone_toggle(request, pk, mpk):
    org, site = _load(request, pk, edit=True)
    if site is None:
        return redirect("overview")
    with transaction.atomic():
        locked = _locked(site)
        m = get_object_or_404(Milestone, pk=mpk, site=locked)
        if m.completed_at:
            m.completed_at = None
            m.completed_by = None
            action = AuditEvent.Action.MILESTONE_REOPENED
        else:
            m.completed_at = timezone.now()
            m.completed_by = request.user
            action = AuditEvent.Action.MILESTONE_COMPLETED
        m.save(update_fields=["completed_at", "completed_by"])
        record(request.user, org, action, site.pk, _label(site, m), milestone_id=m.pk)
        recompute_progress(locked)
    return redirect("milestones", pk=site.pk)


@login_required
@require_POST
def milestone_edit(request, pk, mpk):
    org, site = _load(request, pk, edit=True)
    if site is None:
        return redirect("overview")
    form = MilestoneForm(request.POST)
    if not form.is_valid():
        messages.error(
            request, "Give the milestone a title (up to 120 characters) and a valid date."
        )
        return redirect("milestones", pk=site.pk)
    with transaction.atomic():
        locked = _locked(site)
        m = get_object_or_404(Milestone, pk=mpk, site=locked)
        title, due = form.cleaned_data["title"], form.cleaned_data["due_date"]
        changed = []
        if title != m.title:
            changed.append("title")
        if due != m.due_date:
            changed.append("due date")
        if changed:
            m.title, m.due_date = title, due
            m.save(update_fields=["title", "due_date"])
            record(
                request.user, org, AuditEvent.Action.MILESTONE_EDITED,
                site.pk, _label(site, m), milestone_id=m.pk, fields=changed,
            )
    messages.success(request, "Milestone saved." if changed else "Nothing changed.")
    return redirect("milestones", pk=site.pk)


@login_required
@require_POST
def milestone_move(request, pk, mpk):
    org, site = _load(request, pk, edit=True)
    if site is None:
        return redirect("overview")
    direction = request.POST.get("direction", "")
    if direction not in ("up", "down"):
        messages.error(request, "Choose up or down.")
        return redirect("milestones", pk=site.pk)
    with transaction.atomic():
        locked = _locked(site)
        items = list(locked.milestones.order_by("position", "id"))
        idx = next((i for i, x in enumerate(items) if x.pk == mpk), None)
        if idx is None:
            raise Http404
        j = idx - 1 if direction == "up" else idx + 1
        if 0 <= j < len(items):
            items[idx], items[j] = items[j], items[idx]
        for pos, item in enumerate(items):
            item.position = pos
        Milestone.objects.bulk_update(items, ["position"])
    return redirect("milestones", pk=site.pk)


@login_required
@require_POST
def milestone_delete(request, pk, mpk):
    org, site = _load(request, pk, edit=True)
    if site is None:
        return redirect("overview")
    with transaction.atomic():
        locked = _locked(site)
        m = get_object_or_404(Milestone, pk=mpk, site=locked)
        if m.is_done:
            messages.error(request, "A completed milestone can’t be deleted. Reopen it first.")
            return redirect("milestones", pk=site.pk)
        label = _label(site, m)
        m.delete()
        record(
            request.user, org, AuditEvent.Action.MILESTONE_DELETED,
            site.pk, label, milestone_id=mpk,
        )
        recompute_progress(locked)
    messages.success(request, "Milestone deleted.")
    return redirect("milestones", pk=site.pk)


@login_required
@require_POST
def milestone_settings(request, pk):
    org, site = _load(request, pk, edit=True)
    if site is None:
        return redirect("overview")
    enabled = request.POST.get("progress_from_milestones") == "on"
    with transaction.atomic():
        locked = _locked(site)
        if enabled != locked.progress_from_milestones:
            Site.objects.filter(pk=locked.pk).update(
                progress_from_milestones=enabled, updated_at=timezone.now()
            )
            locked.progress_from_milestones = enabled
            recompute_progress(locked)
            record(
                request.user, org, AuditEvent.Action.SITE_EDITED,
                site.pk, site.name, fields=["Progress from milestones"],
            )
    messages.success(request, "Saved.")
    return redirect("milestones", pk=site.pk)