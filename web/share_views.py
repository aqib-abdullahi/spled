from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from audit.log import record
from audit.models import AuditEvent
from organisations.permissions import CREATE_SHARE_LINKS, can
from registry.access import sites_for
from registry.models import EvidenceEntry, EvidencePhoto, Site
from sharing.models import MAX_ACTIVE_PER_SITE, ShareLink

from .context import get_current_membership
from .share_forms import ShareForm

ENTRY_LIMIT = 200


# ---------- Staff: manage links ----------

def _load(request, pk):
    membership = get_current_membership(request)
    if not membership:
        return None, None
    org = membership.organisation
    if not can(request.user, CREATE_SHARE_LINKS, org):
        raise PermissionDenied
    site = get_object_or_404(sites_for(request.user).filter(organisation=org), pk=pk)
    return org, site


def _page(request, org, site, form, new_link=None, status=200):
    links = list(site.share_links.select_related("created_by")[:50])
    active_count = site.share_links.filter(
        revoked_at__isnull=True, expires_at__gt=timezone.now()
    ).count()
    return render(request, "share_links.html", {
        "active": "sites", "org": org, "site": site, "form": form,
        "links": links, "new_link": new_link,
        "active_count": active_count, "max_links": MAX_ACTIVE_PER_SITE,
    }, status=status)


@login_required
def share_links(request, pk):
    org, site = _load(request, pk)
    if site is None:
        return redirect("overview")
    new_link = None
    stored = request.session.get("new_share_link")
    if stored and stored.get("site") == site.pk:
        new_link = stored
        del request.session["new_share_link"]
    return _page(request, org, site, ShareForm(), new_link)


@login_required
@require_POST
def share_create(request, pk):
    org, site = _load(request, pk)
    if site is None:
        return redirect("overview")
    form = ShareForm(request.POST)
    if not form.is_valid():
        return _page(request, org, site, form)
    d = form.cleaned_data
    with transaction.atomic():
        Site.objects.select_for_update().get(pk=site.pk)  # so two people can't beat the cap
        active = site.share_links.filter(
            revoked_at__isnull=True, expires_at__gt=timezone.now()
        ).count()
        if active >= MAX_ACTIVE_PER_SITE:
            form.add_error(
                None,
                f"A site can have at most {MAX_ACTIVE_PER_SITE} active links. Revoke one first.",
            )
            return _page(request, org, site, form)
        link, raw = ShareLink.create_for(
            site, d["label"], request.user, d["days"],
            d["include_photos"], d["include_milestones"], d["password"],
        )
        record(
            request.user, org, AuditEvent.Action.SHARE_CREATED, site.pk, site.name,
            label=link.label, link_id=link.pk,
            expires=link.expires_at.date().isoformat(),
            photos=link.include_photos, milestones=link.include_milestones,
            password_protected=link.has_password,
        )
    request.session["new_share_link"] = {
        "site": site.pk,
        "url": request.build_absolute_uri(reverse("share_view", args=[raw])),
    }
    return redirect("share_links", pk=site.pk)


@login_required
@require_POST
def share_revoke(request, pk, lpk):
    org, site = _load(request, pk)
    if site is None:
        return redirect("overview")
    link = get_object_or_404(ShareLink, pk=lpk, site=site, revoked_at__isnull=True)
    with transaction.atomic():
        link.revoked_at = timezone.now()
        link.save(update_fields=["revoked_at"])
        record(
            request.user, org, AuditEvent.Action.SHARE_REVOKED, site.pk, site.name,
            label=link.label, link_id=link.pk,
        )
    messages.success(request, f"The link “{link.label}” was revoked.")
    return redirect("share_links", pk=site.pk)


# ---------- Recipients: open a link ----------

def _guard(response):
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Cache-Control"] = "private, no-store"
    return response


def _unlocked_ids(request):
    return request.session.get("share_unlocked", [])


def _unlock(request, link):
    ids = list(_unlocked_ids(request))
    if link.pk not in ids:
        ids.append(link.pk)
    request.session["share_unlocked"] = ids[-50:]


def _unavailable(request):
    return _guard(render(request, "share_unavailable.html", status=410))


def _password_page(request, link, token, error="", status=200):
    return _guard(render(request, "share_password.html", {
        "org": link.site.organisation, "token": token, "error": error,
    }, status=status))


def share_view(request, token):
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    link = ShareLink.lookup(token)
    if link is None:
        raise Http404
    if not link.is_active:
        return _unavailable(request)

    if link.has_password and link.pk not in _unlocked_ids(request):
        if request.method == "POST":
            result = link.try_password(request.POST.get("password", ""))
            if result == "ok":
                _unlock(request, link)
                return redirect("share_view", token=token)
            if result == "locked":
                return _password_page(
                    request, link, token,
                    "Too many wrong attempts. Try again in 15 minutes.", 429,
                )
            return _password_page(request, link, token, "That password isn’t right.")
        if link.is_locked:
            return _password_page(
                request, link, token, "Too many wrong attempts. Try again in 15 minutes.", 429
            )
        return _password_page(request, link, token)

    if request.method == "POST":
        return HttpResponseNotAllowed(["GET", "HEAD"])

    link.record_view()
    site = link.site
    counted = site.evidence.counted()
    entries = list(
        counted.prefetch_related("photos", "amendments").order_by("-created_at", "-id")[:ENTRY_LIMIT]
    )
    total = counted.count()
    return _guard(render(request, "share_view.html", {
        "link": link, "site": site, "org": site.organisation, "token": token,
        "entries": entries, "entry_total": total, "truncated": total > len(entries),
        "milestones": list(site.milestones.all()) if link.include_milestones else [],
    }))


@require_safe
def share_photo(request, token, pk, variant):
    if variant not in ("display", "thumb"):  # the original is never served
        raise Http404
    link = ShareLink.lookup(token)
    if link is None or not link.is_active or not link.include_photos:
        raise Http404
    if link.has_password and link.pk not in _unlocked_ids(request):
        raise Http404
    photo = get_object_or_404(
        EvidencePhoto.objects.select_related("entry"), pk=pk, entry__site=link.site
    )
    if not EvidenceEntry.objects.counted().filter(pk=photo.entry_id).exists():
        raise Http404
    try:
        with getattr(photo, variant).open("rb") as handle:
            data = handle.read()
    except (FileNotFoundError, ValueError):
        raise Http404
    response = HttpResponse(data, content_type="image/jpeg")
    response["Content-Disposition"] = "inline"
    return _guard(response)