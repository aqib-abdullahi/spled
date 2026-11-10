from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, EvidenceReview, Site

NEAR = {"latitude": 9.0701, "longitude": 7.4001}


def make_site(org, name, **kwargs):
    return Site.objects.create(
        organisation=org, name=name, kind="road",
        location=Point(7.4, 9.07, srid=4326), **kwargs,
    )


class ReviewFlowTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ("admin", "editor", "field", "viewer", "contractor"):
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=role.title()
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.site = make_site(self.org, "Riverside", is_public=True)

    def login(self, role):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def pending(self, body="Trench dug"):
        return EvidenceEntry.objects.create(
            site=self.site, author=self.users["contractor"], kind="note", body=body,
            needs_review=True, location=Point(7.4001, 9.0701, srid=4326),
        )

    def log(self, role, **extra):
        self.login(role)
        data = {"kind": "note", "body": "Panels in", "tags": "", "latitude": "",
                "longitude": "", "new_status": ""}
        data.update(extra)
        return self.client.post(reverse("evidence_new", args=[self.site.pk]), data)

    def decide(self, role, entry, decision, comment=""):
        self.login(role)
        return self.client.post(
            reverse("review_decide", args=[entry.pk]),
            {"decision": decision, "comment": comment},
        )

    def public_page(self):
        self.client.logout()
        return self.client.get(reverse("project", args=[self.site.pk]))

    def test_contractor_can_log_and_the_entry_is_flagged(self):
        r = self.log("contractor", **NEAR)
        self.assertRedirects(r, reverse("site_detail", args=[self.site.pk]))
        entry = EvidenceEntry.objects.get()
        self.assertTrue(entry.needs_review)
        self.assertEqual(entry.author, self.users["contractor"])

    def test_contractor_cannot_change_status(self):
        self.log("contractor", new_status="delayed", **NEAR)
        self.site.refresh_from_db()
        self.assertEqual(self.site.status, "planned")
        self.assertEqual(EvidenceEntry.objects.get().kind, "note")

    def test_field_entries_need_no_review(self):
        self.log("field", **NEAR)
        self.assertFalse(EvidenceEntry.objects.get().needs_review)

    def test_pending_entries_stay_off_the_public_page(self):
        self.pending("Trench dug")
        self.assertNotContains(self.public_page(), "Trench dug")

    def test_approved_entries_appear_publicly(self):
        entry = self.pending("Trench dug")
        EvidenceReview.objects.create(
            entry=entry, reviewer=self.users["editor"], decision="approved"
        )
        self.assertContains(self.public_page(), "Trench dug")

    def test_rejected_entries_stay_hidden(self):
        entry = self.pending("Trench dug")
        EvidenceReview.objects.create(
            entry=entry, reviewer=self.users["editor"],
            decision="rejected", comment="Wrong site",
        )
        self.assertNotContains(self.public_page(), "Trench dug")

    def test_queue_is_for_approvers_only(self):
        for role in ("field", "viewer", "contractor"):
            self.login(role)
            self.assertEqual(self.client.get(reverse("review")).status_code, 403, role)
        for role in ("admin", "editor"):
            self.login(role)
            self.assertEqual(self.client.get(reverse("review")).status_code, 200, role)

    def test_queue_shows_pending_entries_to_an_editor(self):
        self.pending("Trench dug")
        self.login("editor")
        self.assertContains(self.client.get(reverse("review")), "Trench dug")

    def test_approve_creates_a_review(self):
        entry = self.pending()
        r = self.decide("editor", entry, "approved")
        self.assertRedirects(r, reverse("review"))
        self.assertEqual(EvidenceReview.objects.get(entry=entry).decision, "approved")

    def test_reject_needs_a_reason(self):
        entry = self.pending()
        self.decide("editor", entry, "rejected", "")
        self.assertFalse(EvidenceReview.objects.exists())

    def test_reject_with_a_reason(self):
        entry = self.pending()
        self.decide("editor", entry, "rejected", "Photo is of another site")
        review = EvidenceReview.objects.get(entry=entry)
        self.assertEqual(review.decision, "rejected")
        self.assertEqual(review.comment, "Photo is of another site")

    def test_cannot_review_another_organisations_entry(self):
        other_org = Organisation.objects.create(name="Other", kind="private")
        other_site = make_site(other_org, "Theirs")
        stranger = User.objects.create_user("s@example.com", "pw12345678", full_name="S")
        theirs = EvidenceEntry.objects.create(
            site=other_site, author=stranger, kind="note", body="x", needs_review=True
        )
        r = self.decide("editor", theirs, "approved")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(EvidenceReview.objects.exists())

    def test_already_reviewed_entry_is_not_changed(self):
        entry = self.pending()
        EvidenceReview.objects.create(
            entry=entry, reviewer=self.users["editor"], decision="approved"
        )
        self.decide("admin", entry, "rejected", "Too late")
        self.assertEqual(EvidenceReview.objects.get(entry=entry).decision, "approved")

    def test_anonymous_is_sent_to_sign_in(self):
        self.assertEqual(self.client.get(reverse("review")).status_code, 302)

    def test_navigation_shows_the_pending_count_to_approvers(self):
        self.pending()
        self.login("editor")
        self.assertContains(
            self.client.get(reverse("sites")), '<span class="count">1</span>'
        )
        self.login("field")
        self.assertNotContains(self.client.get(reverse("sites")), 'class="count"')