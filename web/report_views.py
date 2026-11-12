from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from audit.log import record
from audit.models import AuditEvent
from organisations.permissions import EXPORT_REPORTS, can
from registry.access import sites_for
from registry.models import Site
from registry.reports import (
    annotate_portfolio,
    build_site_report,
    render_markdown,
    write_portfolio_csv,
)

from .context import get_current_membership


class ReportForm(forms.Form):
    site = forms.ModelChoiceField(
        queryset=Site.objects.none(), empty_label="Choose a site…", label="Site"
    )
    date_from = forms.DateField(
        required=False, label="From",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    date_to = forms.DateField(
        required=False, label="To",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, sites, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["site"].queryset = sites

    def clean(self):
        data = super().clean()
        start, end = data.get("date_from"), data.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError(
                "The start date must be on or before the end date."
            )
        return data


def _gate(request):
    membership = get_current_membership(request)
    if not membership:
        return None, None
    org = membership.organisation
    if not can(request.user, EXPORT_REPORTS, org):
        raise PermissionDenied
    sites = sites_for(request.user).filter(organisation=org).order_by("name")
    return org, sites


def _iso(value):
    return value.isoformat() if value else ""


@login_required
def reports_page(request):
    org, sites = _gate(request)
    if org is None:
        return redirect("overview")
    return render(request, "reports.html", {
        "active": "reports", "org": org,
        "form": ReportForm(sites=sites), "site_count": sites.count(),
    })


@login_required
def report_site(request):
    org, sites = _gate(request)
    if org is None:
        return redirect("overview")
    form = (
        ReportForm(request.GET, sites=sites)
        if "site" in request.GET
        else ReportForm(sites=sites)
    )
    if not form.is_bound or not form.is_valid():
        return render(request, "reports.html", {
            "active": "reports", "org": org, "form": form, "site_count": sites.count(),
        })
    d = form.cleaned_data
    report = build_site_report(
        d["site"], d["date_from"], d["date_to"], generated_by=request.user
    )
    return render(request, "report_site.html", {
        "active": "reports", "org": org, "report": report,
        "site": d["site"], "start": d["date_from"], "end": d["date_to"],
    })


@login_required
@require_POST
def report_site_download(request):
    org, sites = _gate(request)
    if org is None:
        return redirect("overview")
    form = ReportForm(request.POST, sites=sites)
    if not form.is_valid():
        messages.error(request, "Choose a site and a valid date range.")
        return redirect("reports")
    d = form.cleaned_data
    site = d["site"]
    report = build_site_report(
        site, d["date_from"], d["date_to"], generated_by=request.user
    )
    body = render_markdown(report)
    record(
        request.user, org, AuditEvent.Action.REPORT_EXPORTED, site.pk, site.name,
        kind="site_markdown", entries=report["entry_total"],
        date_from=_iso(d["date_from"]), date_to=_iso(d["date_to"]),
    )
    filename = f"{slugify(site.name) or 'site'}-report-{timezone.localdate().isoformat()}.md"
    response = HttpResponse(body, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_POST
def report_portfolio_csv(request):
    org, sites = _gate(request)
    if org is None:
        return redirect("overview")
    filename = f"spled-portfolio-{org.slug}-{timezone.localdate().isoformat()}.csv"
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    rows = write_portfolio_csv(response, list(annotate_portfolio(sites)))
    record(
        request.user, org, AuditEvent.Action.REPORT_EXPORTED, None, "Portfolio CSV",
        kind="portfolio_csv", rows=rows,
    )
    return response