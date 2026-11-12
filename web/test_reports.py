import csv
import datetime
import io
from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, Milestone, Site
from registry.reports import CSV_COLUMNS

ROLES = ("admin", "editor", "owner", "field", "viewer", "contractor")
ALLOWED = ("admin", "editor", "owner")
DENIED = ("field", "viewer", "contractor")


def make_site(org, name, **kwargs):
    return Site.objects.create(
        organisation=org, name=name, kind="road",
        location=Point(7.4, 9.07, srid=4326), **kwargs,
    )


class ReportViewTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ROLES:
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=f"Zed {role.title()}"
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.site = make_site(self.org, "Riverside")
        Milestone.objects.create(site=self.site, title="Site survey")
        EvidenceEntry.objects.create(
            site=self.site, author=self.users["editor"], kind="note",
            body="Poured foundations", location=Point(7.4001, 9.0701, srid=4326),
        )
        EvidenceEntry.objects.create(
            site=self.site, author=self.users["contractor"], kind="note",
            body="Trench pending", needs_review=True,
        )
        other = Organisation.objects.create(
            name="Other", kind="private", verification="verified"
        )
        self.theirs = make_site(other, "Theirs")

    def login(self, role="editor"):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def table(self, response):
        text = response.content.decode("utf-8")
        return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))

    def post_csv(self):
        return self.client.post(reverse("report_portfolio_csv"))

    def post_md(self, **extra):
        data = {"site": self.site.pk, "date_from": "", "date_to": ""}
        data.update(extra)
        return self.client.post(reverse("report_site_download"), data)

    def view_report(self, **params):
        query = {"site": self.site.pk}
        query.update(params)
        return self.client.get(reverse("report_site"), query)

    def test_reports_page_needs_sign_in(self):
        self.assertEqual(self.client.get(reverse("reports")).status_code, 302)

    def test_who_can_open_the_reports_page(self):
        for role in ALLOWED:
            self.login(role)
            self.assertEqual(self.client.get(reverse("reports")).status_code, 200, role)
        for role in DENIED:
            self.login(role)
            self.assertEqual(self.client.get(reverse("reports")).status_code, 403, role)

    def test_the_nav_link_is_for_exporters_only(self):
        self.login("editor")
        self.assertContains(self.client.get(reverse("sites")), reverse("reports"))
        self.login("field")
        self.assertNotContains(self.client.get(reverse("sites")), reverse("reports"))

    def test_portfolio_csv_download(self):
        self.login("editor")
        r = self.post_csv()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn('attachment; filename="spled-portfolio-mine-', r["Content-Disposition"])
        self.assertTrue(r.content.decode("utf-8").startswith("\ufeff"))
        rows = self.table(r)
        self.assertEqual(rows[0], CSV_COLUMNS)
        self.assertEqual(rows[1][1], "Riverside")
        self.assertEqual(rows[1][CSV_COLUMNS.index("evidence_entries")], "1")
        self.assertEqual(rows[1][CSV_COLUMNS.index("awaiting_review")], "1")

    def test_downloads_only_accept_post(self):
        self.login("editor")
        self.assertEqual(self.client.get(reverse("report_portfolio_csv")).status_code, 405)
        self.assertEqual(self.client.get(reverse("report_site_download")).status_code, 405)

    def test_roles_without_permission_cannot_download(self):
        for role in DENIED:
            self.login(role)
            self.assertEqual(self.post_csv().status_code, 403, role)
            self.assertEqual(self.post_md().status_code, 403, role)
            self.assertEqual(self.view_report().status_code, 403, role)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_csv_lists_only_this_organisations_active_sites(self):
        old = make_site(self.org, "Old Road")
        old.archive()
        self.login("editor")
        names = [row[1] for row in self.table(self.post_csv())[1:]]
        self.assertEqual(names, ["Riverside"])

    def test_csv_neutralises_formulas(self):
        make_site(self.org, '=HYPERLINK("http://evil.example","x")', owner_name="@owner")
        self.login("editor")
        rows = self.table(self.post_csv())[1:]
        bad = next(r for r in rows if "HYPERLINK" in r[1])
        self.assertTrue(bad[1].startswith("'="))
        self.assertEqual(bad[4], "'@owner")

    def test_csv_export_is_logged(self):
        self.login("editor")
        self.post_csv()
        event = AuditEvent.objects.get(action="report.exported")
        self.assertEqual(event.detail["kind"], "portfolio_csv")
        self.assertEqual(event.detail["rows"], 1)
        self.assertEqual(event.organisation, self.org)
        self.assertIn("editor@example.com", event.actor_label)

    def test_site_report_page_shows_the_record(self):
        self.login("editor")
        r = self.view_report()
        self.assertContains(r, "Riverside")
        self.assertContains(r, "Poured foundations")
        self.assertContains(r, "Verified on site")
        self.assertContains(r, "Site survey")
        self.assertContains(r, "Download Markdown")
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_site_report_only_shows_counted_entries(self):
        self.login("editor")
        r = self.view_report()
        self.assertNotContains(r, "Trench pending")
        self.assertContains(r, "awaiting review")

    def test_site_report_for_another_organisation_is_refused(self):
        self.login("editor")
        r = self.client.get(reverse("report_site"), {"site": self.theirs.pk})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Theirs")
        self.assertNotContains(r, "Download Markdown")

    def test_bad_dates_are_refused(self):
        self.login("editor")
        r = self.view_report(date_from="not-a-date")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Enter a valid date")
        self.assertNotContains(r, "Download Markdown")

    def test_start_after_end_is_refused(self):
        self.login("editor")
        r = self.view_report(date_from="2026-10-01", date_to="2026-09-01")
        self.assertContains(r, "on or before the end date")
        self.assertNotContains(r, "Download Markdown")

    def test_markdown_download(self):
        self.login("editor")
        r = self.post_md()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/markdown; charset=utf-8")
        self.assertIn('attachment; filename="riverside-report-', r["Content-Disposition"])
        body = r.content.decode("utf-8")
        self.assertIn("# Riverside", body)
        self.assertIn("> Poured foundations", body)
        self.assertNotIn("Trench pending", body)

    def test_markdown_download_is_logged(self):
        self.login("editor")
        self.post_md(date_from="2020-01-01")
        event = AuditEvent.objects.get(action="report.exported")
        self.assertEqual(event.detail["kind"], "site_markdown")
        self.assertEqual(event.detail["entries"], 1)
        self.assertEqual(event.detail["date_from"], "2020-01-01")
        self.assertEqual(event.target_id, self.site.pk)
        self.assertEqual(event.target_label, "Riverside")

    def test_invalid_markdown_request_downloads_nothing(self):
        self.login("editor")
        r = self.post_md(site=self.theirs.pk)
        self.assertRedirects(r, reverse("reports"))
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_site_report_date_range(self):
        old = datetime.datetime(2020, 8, 1, 12, 0, tzinfo=datetime.timezone.utc)
        with mock.patch("registry.models.timezone.now", return_value=old):
            EvidenceEntry.objects.create(
                site=self.site, author=self.users["editor"], kind="note", body="Old entry"
            )
        self.login("editor")
        everything = self.view_report()
        self.assertContains(everything, "Old entry")
        self.assertContains(everything, "Poured foundations")
        recent = self.view_report(date_from="2021-01-01")
        self.assertNotContains(recent, "Old entry")
        self.assertContains(recent, "Poured foundations")

    def test_exports_show_in_the_audit_log(self):
        self.login("admin")
        self.post_csv()
        r = self.client.get(reverse("audit_log"))
        self.assertContains(r, "Report exported")