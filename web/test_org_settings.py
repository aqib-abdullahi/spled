from datetime import timedelta

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from organisations.models import Membership, Organisation
from registry.models import Site


class OrgSettingsTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ("admin", "editor", "field"):
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=role.title()
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.url = reverse("org_settings")

    def login(self, role="admin"):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def data(self, **extra):
        d = {
            "name": "Mine",
            "public_name": "",
            "stale_after_days": 21,
            "require_onsite_for_status_changes": "on",
        }
        d.update(extra)
        return {k: v for k, v in d.items() if v is not None}

    def save(self, **extra):
        self.login()
        return self.client.post(self.url, self.data(**extra))

    def refresh(self):
        self.org.refresh_from_db()
        return self.org

    def site_data(self, **extra):
        d = {
            "name": "New Road", "kind": "road", "status": "planned",
            "owner_name": "", "target_date": "", "progress": 0,
            "latitude": 9.07, "longitude": 7.4, "description": "",
        }
        d.update(extra)
        return d

    def test_page_is_for_admins_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        for role in ("editor", "field"):
            self.login(role)
            self.assertEqual(self.client.get(self.url).status_code, 403, role)
        self.login("admin")
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_page_shows_current_values(self):
        self.login()
        r = self.client.get(self.url)
        self.assertContains(r, "Mine")
        self.assertContains(r, "Verified")
        self.assertContains(r, 'value="21"')

    def test_admin_can_save_settings(self):
        r = self.save(
            name="Ministry of Works", public_name="Works", stale_after_days=30,
            require_onsite_for_status_changes=None,
            publish_new_sites_automatically="on",
        )
        self.assertRedirects(r, self.url)
        org = self.refresh()
        self.assertEqual(org.name, "Ministry of Works")
        self.assertEqual(org.public_name, "Works")
        self.assertEqual(org.stale_after_days, 30)
        self.assertFalse(org.require_onsite_for_status_changes)
        self.assertTrue(org.publish_new_sites_automatically)
        self.assertEqual(AuditEvent.objects.get().action, "org.settings_changed")

    def test_audit_event_lists_only_changed_fields(self):
        self.save(stale_after_days=30)
        event = AuditEvent.objects.get()
        self.assertEqual(len(event.detail["fields"]), 1)
        self.assertIn("days", event.detail["fields"][0])

    def test_unchanged_save_logs_nothing(self):
        self.save()
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_name_is_required(self):
        r = self.save(name="")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.refresh().name, "Mine")
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_stale_days_must_be_between_1_and_365(self):
        for bad in ("0", "366", "-5", "abc", ""):
            r = self.save(stale_after_days=bad)
            self.assertEqual(r.status_code, 200, bad)
            self.assertEqual(self.refresh().stale_after_days, 21, bad)
        self.assertEqual(self.save(stale_after_days=365).status_code, 302)
        self.assertEqual(self.refresh().stale_after_days, 365)

    def test_verification_and_type_cannot_be_changed_here(self):
        self.save(verification="rejected", kind="private", slug="hijacked")
        org = self.refresh()
        self.assertEqual(org.verification, "verified")
        self.assertEqual(org.kind, "government")
        self.assertNotEqual(org.slug, "hijacked")

    def test_only_the_current_organisation_is_changed(self):
        other = Organisation.objects.create(name="Other", kind="private")
        stranger = User.objects.create_user("s@example.com", "pw12345678", full_name="S")
        Membership.objects.create(user=stranger, organisation=other, role="admin")
        self.save(name="Renamed", organisation=other.pk, id=other.pk)
        other.refresh_from_db()
        self.assertEqual(other.name, "Other")
        self.assertEqual(self.refresh().name, "Renamed")

    def test_stale_setting_changes_the_dashboard(self):
        site = Site.objects.create(
            organisation=self.org, name="Quiet Road", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        Site.objects.filter(pk=site.pk).update(
            created_at=timezone.now() - timedelta(days=3)
        )
        self.login()
        self.assertEqual(self.client.get(reverse("overview")).context["attention_count"], 0)
        self.client.post(self.url, self.data(stale_after_days=2))
        self.assertEqual(self.client.get(reverse("overview")).context["attention_count"], 1)

    def test_onsite_rule_can_be_switched_off(self):
        site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        far = {
            "kind": "note", "body": "Moved on", "tags": "",
            "latitude": 9.5, "longitude": 7.9, "new_status": "delayed",
        }
        evidence = reverse("evidence_new", args=[site.pk])
        self.login("editor")
        self.client.post(evidence, far)
        site.refresh_from_db()
        self.assertEqual(site.status, "planned")  # refused while the rule is on
        self.save(require_onsite_for_status_changes=None)
        self.login("editor")
        self.client.post(evidence, far)
        site.refresh_from_db()
        self.assertEqual(site.status, "delayed")

    def test_new_sites_stay_private_by_default(self):
        self.login()
        self.client.post(reverse("site_new"), self.site_data())
        self.assertFalse(Site.objects.get(name="New Road").is_public)

    def test_auto_publish_makes_new_sites_public(self):
        self.save(publish_new_sites_automatically="on")
        self.login()
        self.client.post(reverse("site_new"), self.site_data())
        self.assertTrue(Site.objects.get(name="New Road").is_public)

    def test_auto_publish_does_nothing_for_an_unverified_organisation(self):
        self.save(publish_new_sites_automatically="on")
        Organisation.objects.filter(pk=self.org.pk).update(verification="pending")
        self.login()
        self.client.post(reverse("site_new"), self.site_data())
        self.assertFalse(Site.objects.get(name="New Road").is_public)

    def test_auto_publish_is_logged(self):
        self.save(publish_new_sites_automatically="on")
        self.login()
        self.client.post(reverse("site_new"), self.site_data())
        event = AuditEvent.objects.get(action="site.created")
        self.assertTrue(event.detail["auto_published"])

    def test_public_name_is_shown_on_the_public_page(self):
        site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="road", is_public=True,
            location=Point(7.4, 9.07, srid=4326),
        )
        self.save(public_name="Ministry of Works")
        self.client.logout()
        r = self.client.get(reverse("project", args=[site.pk]))
        self.assertContains(r, "Ministry of Works")

    def test_the_menu_link_is_for_admins_only(self):
        self.login("admin")
        self.assertContains(self.client.get(reverse("sites")), self.url)
        self.login("editor")
        self.assertNotContains(self.client.get(reverse("sites")), self.url)