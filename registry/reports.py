import csv

from django.db.models import Count, Max, Q
from django.utils import timezone

from .access import COUNTED
from .models import EvidenceEntry

ENTRY_LIMIT = 500

CSV_COLUMNS = [
    "id", "name", "type", "status", "owner", "target_date", "progress_percent",
    "latitude", "longitude", "boundary_hectares", "published",
    "milestones_done", "milestones_total", "evidence_entries",
    "verified_on_site_entries", "awaiting_review", "last_evidence_at", "created_at",
]

_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
_MD_SPECIAL = set("\\`*_[]<>|#!")


def safe_cell(value):
    """Stop spreadsheets treating text as a formula."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(_DANGEROUS) else text


def md_text(value):
    """Escape characters that Markdown would treat as formatting."""
    return "".join("\\" + c if c in _MD_SPECIAL else c for c in str(value or ""))


def _line(value):
    return md_text(" ".join(str(value or "").split()))


def _quote(value):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(
        "> " + md_text(line) if line.strip() else ">" for line in text.split("\n")
    )


def _stamp(value):
    if value is None:
        return ""
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M")


def _when(value):
    return timezone.localtime(value).strftime("%d %b %Y, %H:%M")


def _day(value):
    return value.strftime("%d %b %Y")


def _period(start, end):
    if start and end:
        return f"{_day(start)} to {_day(end)}"
    if start:
        return f"from {_day(start)}"
    if end:
        return f"up to {_day(end)}"
    return "all time"


# ---------- Portfolio CSV ----------

def annotate_portfolio(sites):
    return sites.annotate(
        evidence_count=Count("evidence", filter=COUNTED, distinct=True),
        verified_count=Count(
            "evidence",
            filter=COUNTED & Q(evidence__verified_on_site=True),
            distinct=True,
        ),
        pending_count=Count(
            "evidence",
            filter=Q(evidence__needs_review=True, evidence__review__isnull=True),
            distinct=True,
        ),
        milestones_total=Count("milestones", distinct=True),
        milestones_done=Count(
            "milestones",
            filter=Q(milestones__completed_at__isnull=False),
            distinct=True,
        ),
        last_evidence=Max("evidence__created_at", filter=COUNTED),
    ).order_by("name", "id")


def csv_row(site):
    area = site.area_hectares
    return [
        site.pk,
        safe_cell(site.name),
        site.get_kind_display(),
        site.get_status_display(),
        safe_cell(site.owner_name),
        site.target_date.isoformat() if site.target_date else "",
        site.progress,
        f"{site.location.y:.6f}",
        f"{site.location.x:.6f}",
        f"{area:.2f}" if area is not None else "",
        "yes" if site.is_public else "no",
        site.milestones_done,
        site.milestones_total,
        site.evidence_count,
        site.verified_count,
        site.pending_count,
        _stamp(site.last_evidence),
        _stamp(site.created_at),
    ]


def write_portfolio_csv(fileobj, sites):
    """Write the CSV (with a byte-order mark so Excel reads accents correctly).
    Returns the number of site rows."""
    fileobj.write("\ufeff")
    writer = csv.writer(fileobj)
    writer.writerow(CSV_COLUMNS)
    rows = 0
    for site in sites:
        writer.writerow(csv_row(site))
        rows += 1
    return rows


# ---------- Site report ----------

def build_site_report(site, start=None, end=None, limit=ENTRY_LIMIT, generated_by=None):
    entries = (
        site.evidence.counted()
        .select_related("author")
        .prefetch_related("photos", "amendments")
        .order_by("-created_at", "-id")
    )
    if start:
        entries = entries.filter(created_at__date__gte=start)
    if end:
        entries = entries.filter(created_at__date__lte=end)
    total = entries.count()
    shown = list(entries[:limit])
    return {
        "site": site,
        "org": site.organisation,
        "start": start,
        "end": end,
        "generated_at": timezone.now(),
        "generated_by": generated_by,
        "area": site.area_hectares,
        "milestones": list(site.milestones.all()),
        "entries": shown,
        "entry_total": total,
        "truncated": total > len(shown),
        "pending": site.evidence.filter(needs_review=True, review__isnull=True).count(),
        "chain_ok": not EvidenceEntry.verify_chain(site),
    }


def render_markdown(report):
    site, org = report["site"], report["org"]
    blocks = [
        f"# {_line(site.name)}",
        f"Evidence report for {_line(org.name)}. "
        f"Period: {_period(report['start'], report['end'])}.",
    ]

    facts = [
        f"- **Status:** {site.get_status_display()}",
        f"- **Type:** {site.get_kind_display()}",
    ]
    if site.owner_name:
        facts.append(f"- **Owner:** {_line(site.owner_name)}")
    facts.append(f"- **Progress:** {site.progress}%")
    facts.append(
        "- **Target date:** " + (_day(site.target_date) if site.target_date else "not set")
    )
    facts.append(f"- **Location:** {site.location.y:.6f}, {site.location.x:.6f}")
    if report["area"] is not None:
        facts.append(f"- **Boundary:** {report['area']:.1f} ha")
    facts.append(
        "- **Published to the public portal:** " + ("yes" if site.is_public else "no")
    )
    blocks.append("\n".join(facts))

    blocks.append("## Milestones")
    if report["milestones"]:
        lines = []
        for m in report["milestones"]:
            if m.completed_at:
                done = _day(timezone.localtime(m.completed_at))
                lines.append(f"- [x] {_line(m.title)} (done {done})")
            else:
                due = f" (due {_day(m.due_date)})" if m.due_date else ""
                lines.append(f"- [ ] {_line(m.title)}{due}")
        blocks.append("\n".join(lines))
    else:
        blocks.append("No milestones.")

    blocks.append("## Evidence")
    entries = report["entries"]
    if not entries:
        blocks.append("No evidence in this period.")
    else:
        total = report["entry_total"]
        if report["truncated"]:
            blocks.append(
                f"Showing the newest {len(entries)} of {total} entries in this period. "
                "Narrow the date range to see the rest."
            )
        else:
            blocks.append(f"{total} entr{'y' if total == 1 else 'ies'} in this period.")
        for e in entries:
            if e.verified_on_site:
                verdict = "Verified on site"
            elif e.location:
                verdict = "Not verified on site"
            else:
                verdict = "No location"
            blocks.append(f"### {_when(e.created_at)} · {e.get_kind_display()} · {verdict}")
            blocks.append(_quote(e.body))
            meta = [f"Logged by {_line(e.author.full_name)}"]
            if e.distance_to_site_m is not None:
                meta.append(f"{e.distance_to_site_m:.0f} m from the site pin")
            if e.tags:
                meta.append("Tags: " + ", ".join(_line(t) for t in e.tags))
            blocks.append(" · ".join(meta))
            if e.amends_id:
                blocks.append(
                    f"Correction of an earlier entry. Reason: {_line(e.amendment_reason)}"
                )
            if list(e.amendments.all()):
                blocks.append("Amended by a later correction.")
            photos = list(e.photos.all())
            if photos:
                blocks.append(
                    "Photo fingerprints (SHA-256):\n"
                    + "\n".join(f"- `{p.sha256}`" for p in photos)
                )

    blocks.append("---")
    generated = f"Generated {_when(report['generated_at'])}"
    if report["generated_by"]:
        generated += f" by {_line(report['generated_by'].full_name)}"
    blocks.append(generated + ".")
    chain = (
        "intact"
        if report["chain_ok"]
        else "FAILED its integrity check. Contact an administrator."
    )
    blocks.append(f"Evidence chain check: {chain}")
    blocks.append(f"Entries awaiting review (not included): {report['pending']}")
    return "\n\n".join(blocks) + "\n"