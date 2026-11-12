import csv
import datetime
import io
import shutil
import tempfile
from unittest import mock

from django.contrib.gis.geos import Point, Polygon
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import User
from organisations.models import Organisation

from .models import EvidenceEntry, EvidencePhoto, EvidenceReview, Milestone, Site
from .photos import process_image
from .reports import (
    CSV_COLUMNS,
    annotate_portfolio,
    build_site_report,
    md_text,
    render_markdown,
    safe_cell,
    write_portfolio_csv,
)
from .testing import image_bytes

TMP = tempfile.mkdtemp()
UTC = datetime.timezone.utc
RING = (
    (7.3995, 9.0695), (7.4005, 9.0695), (7.4005, 9.0705),
    (7.3995, 9.0705), (7.3995, 9.0695),
)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


class CellTests(SimpleTestCase):
    def test_formula_starts_are_neutralised(self):
        for text in ("=1+1", "+SUM(A1)", "-2+3", "@cmd", "\tx", "\rx"):
            self.assertEqual(safe_cell(text), "'" + text)

    def test_normal_text_is_unchanged(self):
        self.assertEqual(safe_cell("Riverside Road"), "Riverside Road")
        self.assertEqual(safe_cell("a=b"), "a=b")
        self.assertEqual(safe_cell(None), "")

    def test_markdown_specials_are_escaped(self):
        self.assertEqual(
            md_text("a*b_c [x](y) <b>"), "a\\*b\\_c \\[x\\](y) \\<b\\>"
        )

    def test_markdown_escape_handles_none(self):
        self.assertEqual(md_text(None), "")


class PortfolioTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Org", kind="government", verification="verified"
        )
        self.user = User.objects.create_user("a@example.com", "pw12345678", full_name="Ada")
        self.crew = User.objects.create_user("c@example.com", "pw12345678", full_name="Crew")
        self.site = self.make_site(
            "Riverside", kind="power", status="in_progress", owner_name="Energy Agency",
            progress=71, target_date=datetime.date(2027, 1, 12), is_public=True,
            boundary=Polygon(RING, srid=4326),
        )

    def make_site(self, name, lon=7.4, lat=9.07, **kwargs):
        kwargs.setdefault("kind", "road")
        return Site.objects.create(
            organisation=self.org, name=name,
            location=Point(lon, lat, srid=4326), **kwargs,
        )

    def entry(self, site=None, author=None, needs_review=False, located=True):
        return EvidenceEntry.objects.create(
            site=site or self.site, author=author or self.user, kind="note", body="x",
            needs_review=needs_review,
            location=Point(7.4001, 9.0701, srid=4326) if located else None,
        )

    def table(self):
        buffer = io.StringIO()
        write_portfolio_csv(buffer, annotate_portfolio(Site.objects.all()))
        self.raw = buffer.getvalue()
        return list(csv.reader(io.StringIO(self.raw.lstrip("\ufeff"))))

    def row(self, name="Riverside"):
        rows = self.table()
        return next(dict(zip(CSV_COLUMNS, r)) for r in rows[1:] if r[1] == name or r[1] == "'" + name)

    def test_header_and_byte_order_mark(self):
        rows = self.table()
        self.assertTrue(self.raw.startswith("\ufeff"))
        self.assertEqual(rows[0], CSV_COLUMNS)
        self.assertEqual(len(rows), 2)

    def test_row_values(self):
        Milestone.objects.create(site=self.site, title="Survey", completed_at="2026-08-02T10:00:00Z")
        Milestone.objects.create(site=self.site, title="Build")
        self.entry()
        row = self.row()
        self.assertEqual(row["type"], "Power")
        self.assertEqual(row["status"], "In progress")
        self.assertEqual(row["owner"], "Energy Agency")
        self.assertEqual(row["target_date"], "2027-01-12")
        self.assertEqual(row["progress_percent"], "71")
        self.assertEqual(row["latitude"], "9.070000")
        self.assertEqual(row["longitude"], "7.400000")
        self.assertTrue(row["boundary_hectares"].startswith("1.2"))
        self.assertEqual(row["published"], "yes")
        self.assertEqual((row["milestones_done"], row["milestones_total"]), ("1", "2"))
        self.assertEqual(row["evidence_entries"], "1")
        self.assertNotEqual(row["last_evidence_at"], "")

    def test_only_counted_evidence_is_counted(self):
        self.entry()                                   # counts, verified
        self.entry(located=False)                      # counts, not verified
        self.entry(author=self.crew, needs_review=True)  # pending
        rejected = self.entry(author=self.crew, needs_review=True)
        EvidenceReview.objects.create(
            entry=rejected, reviewer=self.user, decision="rejected", comment="Wrong site"
        )
        approved = self.entry(author=self.crew, needs_review=True)
        EvidenceReview.objects.create(entry=approved, reviewer=self.user, decision="approved")
        row = self.row()
        self.assertEqual(row["evidence_entries"], "3")
        self.assertEqual(row["verified_on_site_entries"], "2")
        self.assertEqual(row["awaiting_review"], "1")

    def test_formulas_in_names_are_neutralised(self):
        self.make_site("=cmd|' /C calc'!A0", owner_name="@owner")
        rows = self.table()
        formula = next(r for r in rows[1:] if "cmd" in r[1])
        self.assertEqual(formula[1], "'=cmd|' /C calc'!A0")
        self.assertEqual(formula[4], "'@owner")

    def test_negative_coordinates_are_not_altered(self):
        self.make_site("South West", lon=-3.5, lat=-1.2)
        row = self.row("South West")
        self.assertEqual(row["latitude"], "-1.200000")
        self.assertEqual(row["longitude"], "-3.500000")

    def test_counts_are_not_multiplied_by_joins(self):
        for _ in range(3):
            self.entry()
        for i in range(4):
            Milestone.objects.create(site=self.site, title=f"m{i}", position=i)
        row = self.row()
        self.assertEqual(row["evidence_entries"], "3")
        self.assertEqual(row["milestones_total"], "4")
        self.assertEqual(row["milestones_done"], "0")

    def test_site_without_evidence_has_a_blank_last_evidence(self):
        row = self.row()
        self.assertEqual(row["evidence_entries"], "0")
        self.assertEqual(row["last_evidence_at"], "")


class SiteReportTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Org", kind="government", verification="verified"
        )
        self.user = User.objects.create_user("a@example.com", "pw12345678", full_name="Ada")
        self.crew = User.objects.create_user("c@example.com", "pw12345678", full_name="Crew")
        self.site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="power", owner_name="Energy Agency",
            progress=71, location=Point(7.4, 9.07, srid=4326),
        )

    def add(self, body="x", **kwargs):
        kwargs.setdefault("author", self.user)
        kwargs.setdefault("kind", "note")
        return EvidenceEntry.objects.create(site=self.site, body=body, **kwargs)

    def add_at(self, when, body):
        with mock.patch("registry.models.timezone.now", return_value=when):
            return self.add(body)

    def md(self, **kwargs):
        return render_markdown(build_site_report(self.site, generated_by=self.user, **kwargs))

    def test_pending_and_rejected_entries_are_left_out(self):
        self.add("counted")
        self.add("pending", author=self.crew, needs_review=True)
        rejected = self.add("rejected", author=self.crew, needs_review=True)
        EvidenceReview.objects.create(
            entry=rejected, reviewer=self.user, decision="rejected", comment="No"
        )
        report = build_site_report(self.site)
        self.assertEqual([e.body for e in report["entries"]], ["counted"])
        self.assertEqual(report["pending"], 1)

    def test_date_range_is_inclusive(self):
        self.add_at(datetime.datetime(2020, 8, 1, 12, 0, tzinfo=UTC), "August")
        self.add_at(datetime.datetime(2020, 10, 1, 12, 0, tzinfo=UTC), "October")

        def bodies(**kwargs):
            return [e.body for e in build_site_report(self.site, **kwargs)["entries"]]

        self.assertEqual(sorted(bodies()), ["August", "October"])
        self.assertEqual(bodies(start=datetime.date(2020, 9, 1)), ["October"])
        self.assertEqual(bodies(end=datetime.date(2020, 8, 31)), ["August"])
        self.assertEqual(
            bodies(start=datetime.date(2020, 8, 1), end=datetime.date(2020, 8, 1)), ["August"]
        )

    def test_long_reports_are_truncated_to_the_newest(self):
        for i in range(5):
            self.add(f"e{i}")
        report = build_site_report(self.site, limit=2)
        self.assertEqual([e.body for e in report["entries"]], ["e4", "e3"])
        self.assertEqual(report["entry_total"], 5)
        self.assertTrue(report["truncated"])
        self.assertIn("Showing the newest 2 of 5", render_markdown(report))

    def test_markdown_has_the_main_sections(self):
        Milestone.objects.create(
            site=self.site, title="Site survey", completed_at="2026-08-02T10:00:00Z"
        )
        Milestone.objects.create(
            site=self.site, title="Grid connection", due_date=datetime.date(2027, 1, 12), position=1
        )
        self.add("Poured foundations", location=Point(7.4001, 9.0701, srid=4326))
        md = self.md()
        for text in (
            "# Riverside", "**Status:** Planned", "**Owner:** Energy Agency",
            "## Milestones", "- [x] Site survey (done 02 Aug 2026)",
            "- [ ] Grid connection (due 12 Jan 2027)",
            "## Evidence", "> Poured foundations", "Verified on site",
            "Logged by Ada", "Entries awaiting review (not included): 0",
        ):
            self.assertIn(text, md)

    def test_markdown_escapes_user_text(self):
        self.site.name = "A_B"
        self.add("<script>alert(1)</script> *bold* [x](http://e.com)")
        md = self.md()
        self.assertIn("# A\\_B", md)
        self.assertIn("\\<script\\>", md)
        self.assertNotIn("<script>", md)
        self.assertIn("\\*bold\\*", md)

    def test_markdown_shows_amendments(self):
        original = self.add("Rows 1 to 3")
        self.add("Rows 1 and 2", amends=original, amendment_reason="Entered in error")
        md = self.md()
        self.assertIn("Correction of an earlier entry. Reason: Entered in error", md)
        self.assertIn("Amended by a later correction.", md)

    def test_empty_site_renders(self):
        md = self.md()
        self.assertIn("No milestones.", md)
        self.assertIn("No evidence in this period.", md)

    def test_chain_check_is_reported(self):
        self.add("x")
        self.assertIn("Evidence chain check: intact", self.md())


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class PhotoReportTests(TestCase):
    def test_markdown_lists_photo_fingerprints(self):
        org = Organisation.objects.create(name="Org", kind="government")
        user = User.objects.create_user("a@example.com", "pw12345678", full_name="Ada")
        site = Site.objects.create(
            organisation=org, name="S", kind="road", location=Point(7.4, 9.07, srid=4326)
        )
        processed = process_image(SimpleUploadedFile("a.jpg", image_bytes()))
        entry = EvidenceEntry.objects.create(
            site=site, author=user, kind="photo", body="x", photo_hashes=[processed.sha256]
        )
        EvidencePhoto.create_from(entry, processed)
        md = render_markdown(build_site_report(site))
        self.assertIn("Photo fingerprints (SHA-256):", md)
        self.assertIn(f"`{processed.sha256}`", md)