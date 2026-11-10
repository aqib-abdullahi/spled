from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.log import record
from audit.models import AuditEvent
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, Site


class AuditLogTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ("admin", "editor", "field", "contractor"):
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=role.title()
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )

    def login(self, role):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def site_data(self, **extra):
        d = {
            "name": "Riverside", "kind": "road", "status": "planned",
            "owner_name": "", "target_date": "", "progress": 0,
            "latitude": 9.07, "longitude": 7.4, "description": "",
        }
        d.update(extra)
        return d

    def actions(self):
        return list(AuditEvent.objects.order_by("id").values_list("action", flat=True))

    def test_creating_a_site_is_logged(self):
        self.login("editor")
        self.client.post(reverse("site_new"), self.site_data(name="New Road"))
        event = AuditEvent.objects.get()
        self.assertEqual(event.action, "site.created")
        self.assertEqual(event.target_label, "New Road")
        self.assertEqual(event.organisation, self.org)
        self.assertIn("editor@example.com", event.actor_label)

    def test_editing_a_site_logs_the_changed_fields(self):
        self.login("editor")
        self.client.post(
            reverse("site_edit", args=[self.site.pk]), self.site_data(name="Renamed")
        )
        event = AuditEvent.objects.get()
        self.assertEqual(event.action, "site.edited")
        self.assertIn("Name", event.detail["fields"])
        self.assertNotIn("Progress", event.detail["fields"])

    def test_publishing_and_unpublishing_are_logged(self):
        self.login("editor")
        url = reverse("site_publish", args=[self.site.pk])
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(self.actions(), ["site.published", "site.unpublished"])

    def test_a_blocked_publish_leaves_no_event(self):
        self.org.verification = "pending"
        self.org.save()
        self.login("editor")
        self.client.post(reverse("site_publish", args=[self.site.pk]))
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_an_invalid_form_leaves_no_event(self):
        self.login("editor")
        r = self.client.post(reverse("site_new"), self.site_data(latitude=123))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_review_decisions_are_logged(self):
        def pending(body):
            return EvidenceEntry.objects.create(
                site=self.site, author=self.users["contractor"], kind="note",
                body=body, needs_review=True,
            )

        first, second = pending("one"), pending("two")
        self.login("editor")
        self.client.post(
            reverse("review_decide", args=[first.pk]), {"decision": "approved"}
        )
        self.client.post(
            reverse("review_decide", args=[second.pk]),
            {"decision": "rejected", "comment": "Wrong site"},
        )
        self.assertEqual(self.actions(), ["review.approved", "review.rejected"])
        rejected = AuditEvent.objects.get(action="review.rejected")
        self.assertEqual(rejected.summary, "Wrong site")

    def test_an_amendment_is_logged(self):
        original = EvidenceEntry.objects.create(
            site=self.site, author=self.users["field"], kind="note", body="Rows 1 to 3"
        )
        self.login("editor")
        self.client.post(
            reverse("evidence_amend", args=[original.pk]),
            {"body": "Rows 1 and 2", "reason": "Entered in error"},
        )
        event = AuditEvent.objects.get()
        self.assertEqual(event.action, "evidence.amended")
        self.assertEqual(event.summary, "Reason: Entered in error")
        self.assertEqual(event.detail["entry_id"], original.pk)

    def test_only_admins_can_open_the_log(self):
        for role in ("editor", "field", "contractor"):
            self.login(role)
            self.assertEqual(self.client.get(reverse("audit_log")).status_code, 403, role)
        self.login("admin")
        self.assertEqual(self.client.get(reverse("audit_log")).status_code, 200)

    def test_anonymous_is_sent_to_sign_in(self):
        self.assertEqual(self.client.get(reverse("audit_log")).status_code, 302)

    def test_the_log_shows_only_this_organisations_events(self):
        other = Organisation.objects.create(name="Other", kind="private")
        stranger = User.objects.create_user("s@example.com", "pw12345678", full_name="S")
        record(stranger, other, AuditEvent.Action.SITE_CREATED, 99, "Secret Site")
        record(self.users["admin"], self.org, AuditEvent.Action.SITE_CREATED, 1, "Our Site")
        self.login("admin")
        r = self.client.get(reverse("audit_log"))
        self.assertContains(r, "Our Site")
        self.assertNotContains(r, "Secret Site")

    def test_filtering_by_group(self):
        admin = self.users["admin"]
        record(admin, self.org, AuditEvent.Action.SITE_CREATED, 1, "Alpha Road")
        record(admin, self.org, AuditEvent.Action.REVIEW_APPROVED, 1, "Beta Road")
        self.login("admin")
        r = self.client.get(reverse("audit_log"), {"group": "review"})
        self.assertContains(r, "Beta Road")
        self.assertNotContains(r, "Alpha Road")

    def test_the_audit_link_is_for_admins_only(self):
        self.login("admin")
        self.assertContains(self.client.get(reverse("sites")), reverse("audit_log"))
        self.login("editor")
        self.assertNotContains(self.client.get(reverse("sites")), reverse("audit_log"))