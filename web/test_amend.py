from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, Site


class AmendTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ("editor", "field", "viewer", "contractor"):
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=f"Zed {role.title()}"
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        self.original = EvidenceEntry.objects.create(
            site=self.site, author=self.users["field"], kind="note",
            body="Poured rows 1 to 3",
        )

    def login(self, role):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def url(self, entry=None):
        return reverse("evidence_amend", args=[(entry or self.original).pk])

    def amend(self, role="editor", **extra):
        self.login(role)
        data = {"body": "Poured rows 1 and 2 only", "reason": "Entered in error"}
        data.update(extra)
        return self.client.post(self.url(), data)

    def correct_directly(self):
        return EvidenceEntry.objects.create(
            site=self.site, author=self.users["editor"], kind="note",
            body="Poured rows 1 and 2 only", amends=self.original,
            amendment_reason="Entered in error",
        )

    def test_editor_can_amend_and_the_original_is_kept(self):
        r = self.amend()
        self.assertRedirects(r, reverse("site_detail", args=[self.site.pk]))
        fix = EvidenceEntry.objects.get(amends=self.original)
        self.assertEqual(fix.body, "Poured rows 1 and 2 only")
        self.assertEqual(fix.amendment_reason, "Entered in error")
        self.assertEqual(fix.author, self.users["editor"])
        self.original.refresh_from_db()
        self.assertEqual(self.original.body, "Poured rows 1 to 3")

    def test_amendment_is_part_of_the_chain(self):
        self.amend()
        self.assertEqual(EvidenceEntry.verify_chain(self.site), [])

    def test_reason_is_required(self):
        r = self.amend(reason="")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 1)

    def test_unchanged_text_is_refused(self):
        r = self.amend(body="Poured rows 1 to 3")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 1)

    def test_roles_without_permission_are_refused(self):
        for role in ("field", "viewer", "contractor"):
            self.login(role)
            self.assertEqual(self.client.get(self.url()).status_code, 403, role)
            self.assertEqual(
                self.client.post(self.url(), {"body": "x", "reason": "y"}).status_code,
                403, role,
            )
        self.assertEqual(EvidenceEntry.objects.count(), 1)

    def test_anonymous_is_sent_to_sign_in(self):
        self.assertEqual(self.client.get(self.url()).status_code, 302)

    def test_other_organisations_entry_is_404(self):
        other_org = Organisation.objects.create(name="Other", kind="private")
        stranger = User.objects.create_user("s@example.com", "pw12345678", full_name="S")
        other_site = Site.objects.create(
            organisation=other_org, name="Theirs", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        theirs = EvidenceEntry.objects.create(
            site=other_site, author=stranger, kind="note", body="x"
        )
        self.login("editor")
        r = self.client.post(self.url(theirs), {"body": "changed", "reason": "why"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(EvidenceEntry.objects.filter(amends=theirs).count(), 0)

    def test_pending_contractor_entry_cannot_be_amended(self):
        pending = EvidenceEntry.objects.create(
            site=self.site, author=self.users["contractor"], kind="note",
            body="Trench dug", needs_review=True,
        )
        self.login("editor")
        self.assertEqual(self.client.get(self.url(pending)).status_code, 404)

    def test_archived_site_entry_cannot_be_amended(self):
        self.site.archive()
        self.login("editor")
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_timeline_shows_amended_and_correction(self):
        self.correct_directly()
        self.login("editor")
        r = self.client.get(reverse("site_detail", args=[self.site.pk]))
        self.assertContains(r, "Amended")
        self.assertContains(r, "Correction")
        self.assertContains(r, "Entered in error")
        self.assertContains(r, "Amend this entry")

    def test_field_user_sees_no_amend_link(self):
        self.login("field")
        r = self.client.get(reverse("site_detail", args=[self.site.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "/amend/")

    def test_public_page_shows_the_correction_without_names(self):
        self.correct_directly()
        Site.objects.filter(pk=self.site.pk).update(is_public=True)
        r = self.client.get(reverse("project", args=[self.site.pk]))
        self.assertContains(r, "Correction")
        self.assertContains(r, "Amended")
        self.assertContains(r, "Entered in error")
        self.assertNotContains(r, "Zed")
        self.assertNotContains(r, "/amend/")