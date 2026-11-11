import datetime

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from organisations.models import Membership, Organisation
from registry.models import Milestone, Site


class MilestoneViewTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ("editor", "field", "viewer"):
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=f"Zed {role.title()}"
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        self.first = self.add("Site survey")
        self.second = self.add("Foundations")

    def add(self, title, site=None):
        site = site or self.site
        return Milestone.objects.create(
            site=site, title=title, position=site.milestones.count()
        )

    def login(self, role):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def url(self, name, m=None, site=None):
        args = [(site or self.site).pk] + ([m.pk] if m else [])
        return reverse(name, args=args)

    def titles(self):
        return list(self.site.milestones.values_list("title", flat=True))

    def actions(self):
        return list(AuditEvent.objects.order_by("id").values_list("action", flat=True))

    def test_any_member_can_see_the_page_but_only_editors_get_controls(self):
        self.login("viewer")
        r = self.client.get(self.url("milestones"))
        self.assertContains(r, "Site survey")
        self.assertNotContains(r, self.url("milestone_add"))
        self.login("editor")
        r = self.client.get(self.url("milestones"))
        self.assertContains(r, self.url("milestone_add"))

    def test_page_needs_sign_in(self):
        self.assertEqual(self.client.get(self.url("milestones")).status_code, 302)

    def test_other_organisations_site_is_404(self):
        other_org = Organisation.objects.create(name="Other", kind="private")
        theirs = Site.objects.create(
            organisation=other_org, name="Theirs", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        self.login("editor")
        self.assertEqual(
            self.client.get(self.url("milestones", site=theirs)).status_code, 404
        )

    def test_editor_can_add_a_milestone(self):
        self.login("editor")
        r = self.client.post(
            self.url("milestone_add"),
            {"title": "Grid connection", "due_date": "2027-01-12"},
        )
        self.assertRedirects(r, self.url("milestones"))
        m = Milestone.objects.get(title="Grid connection")
        self.assertEqual(m.position, 2)
        self.assertEqual(m.due_date, datetime.date(2027, 1, 12))
        event = AuditEvent.objects.get()
        self.assertEqual(event.action, "milestone.added")
        self.assertEqual(event.target_label, "Riverside: Grid connection")

    def test_adding_needs_a_title(self):
        self.login("editor")
        self.client.post(self.url("milestone_add"), {"title": "", "due_date": ""})
        self.assertEqual(self.site.milestones.count(), 2)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_non_editors_cannot_change_milestones(self):
        calls = [
            (self.url("milestone_add"), {"title": "X"}),
            (self.url("milestone_toggle", self.first), {}),
            (self.url("milestone_edit", self.first), {"title": "X", "due_date": ""}),
            (self.url("milestone_move", self.first), {"direction": "down"}),
            (self.url("milestone_delete", self.first), {}),
            (self.url("milestone_settings"), {"progress_from_milestones": "on"}),
        ]
        for role in ("field", "viewer"):
            self.login(role)
            for url, data in calls:
                self.assertEqual(self.client.post(url, data).status_code, 403, (role, url))
        self.assertEqual(self.titles(), ["Site survey", "Foundations"])
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.assertFalse(Milestone.objects.get(pk=self.first.pk).is_done)

    def test_completing_stamps_the_time_and_the_person(self):
        self.login("editor")
        self.client.post(self.url("milestone_toggle", self.first))
        self.first.refresh_from_db()
        self.assertTrue(self.first.is_done)
        self.assertEqual(self.first.completed_by, self.users["editor"])
        self.assertLess(timezone.now() - self.first.completed_at, datetime.timedelta(minutes=1))
        self.assertEqual(self.actions(), ["milestone.completed"])

    def test_reopening_clears_the_stamp(self):
        self.login("editor")
        url = self.url("milestone_toggle", self.first)
        self.client.post(url)
        self.client.post(url)
        self.first.refresh_from_db()
        self.assertFalse(self.first.is_done)
        self.assertIsNone(self.first.completed_by)
        self.assertEqual(self.actions(), ["milestone.completed", "milestone.reopened"])

    def test_editing_changes_the_title_and_due_date(self):
        self.login("editor")
        self.client.post(
            self.url("milestone_edit", self.first),
            {"title": "Site survey v2", "due_date": "2026-12-01"},
        )
        self.first.refresh_from_db()
        self.assertEqual(self.first.title, "Site survey v2")
        self.assertEqual(self.first.due_date, datetime.date(2026, 12, 1))
        event = AuditEvent.objects.get()
        self.assertEqual(event.action, "milestone.edited")
        self.assertEqual(event.detail["fields"], ["title", "due date"])

    def test_editing_with_no_change_logs_nothing(self):
        self.login("editor")
        self.client.post(
            self.url("milestone_edit", self.first),
            {"title": "Site survey", "due_date": ""},
        )
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_move_swaps_the_order(self):
        self.login("editor")
        self.client.post(self.url("milestone_move", self.second), {"direction": "up"})
        self.assertEqual(self.titles(), ["Foundations", "Site survey"])

    def test_moving_the_first_one_up_does_nothing(self):
        self.login("editor")
        self.client.post(self.url("milestone_move", self.first), {"direction": "up"})
        self.assertEqual(self.titles(), ["Site survey", "Foundations"])

    def test_a_completed_milestone_cannot_be_deleted(self):
        self.login("editor")
        self.client.post(self.url("milestone_toggle", self.first))
        self.client.post(self.url("milestone_delete", self.first))
        self.assertTrue(Milestone.objects.filter(pk=self.first.pk).exists())
        self.assertNotIn("milestone.deleted", self.actions())

    def test_an_open_milestone_can_be_deleted_and_logged(self):
        self.login("editor")
        self.client.post(self.url("milestone_delete", self.second))
        self.assertEqual(self.titles(), ["Site survey"])
        self.assertEqual(self.actions(), ["milestone.deleted"])

    def test_progress_follows_milestones_when_enabled(self):
        Site.objects.filter(pk=self.site.pk).update(progress_from_milestones=True)
        self.login("editor")
        self.client.post(self.url("milestone_toggle", self.first))
        self.site.refresh_from_db()
        self.assertEqual(self.site.progress, 50)
        self.client.post(self.url("milestone_toggle", self.second))
        self.site.refresh_from_db()
        self.assertEqual(self.site.progress, 100)
        self.client.post(self.url("milestone_toggle", self.first))
        self.site.refresh_from_db()
        self.assertEqual(self.site.progress, 50)

    def test_the_setting_can_be_switched_on_and_recomputes(self):
        Milestone.objects.filter(pk=self.first.pk).update(completed_at=timezone.now())
        self.login("editor")
        self.client.post(
            self.url("milestone_settings"), {"progress_from_milestones": "on"}
        )
        self.site.refresh_from_db()
        self.assertTrue(self.site.progress_from_milestones)
        self.assertEqual(self.site.progress, 50)
        event = AuditEvent.objects.get()
        self.assertEqual(event.action, "site.edited")
        self.assertEqual(event.detail["fields"], ["Progress from milestones"])

    def test_a_site_is_limited_to_fifty_milestones(self):
        Milestone.objects.bulk_create(
            [Milestone(site=self.site, title=f"m{i}", position=i + 2) for i in range(48)]
        )
        self.assertEqual(self.site.milestones.count(), 50)
        self.login("editor")
        self.client.post(self.url("milestone_add"), {"title": "One too many"})
        self.assertEqual(self.site.milestones.count(), 50)

    def test_cannot_touch_another_organisations_milestone(self):
        other_org = Organisation.objects.create(name="Other", kind="private")
        theirs_site = Site.objects.create(
            organisation=other_org, name="Theirs", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        theirs = self.add("Secret", site=theirs_site)
        self.login("editor")
        for site in (self.site, theirs_site):
            r = self.client.post(self.url("milestone_toggle", theirs, site=site))
            self.assertEqual(r.status_code, 404)
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_done)

    def test_actions_only_accept_post(self):
        self.login("editor")
        urls = [
            self.url("milestone_add"),
            self.url("milestone_settings"),
            self.url("milestone_toggle", self.first),
            self.url("milestone_edit", self.first),
            self.url("milestone_move", self.first),
            self.url("milestone_delete", self.first),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405, url)

    def test_the_site_page_shows_the_milestones(self):
        self.login("editor")
        r = self.client.get(reverse("site_detail", args=[self.site.pk]))
        self.assertContains(r, "Foundations")
        self.assertContains(r, self.url("milestones"))

    def test_the_public_page_shows_milestones_without_names(self):
        Site.objects.filter(pk=self.site.pk).update(is_public=True)
        self.login("editor")
        self.client.post(self.url("milestone_toggle", self.first))
        self.client.logout()
        r = self.client.get(reverse("project", args=[self.site.pk]))
        self.assertContains(r, "Site survey")
        self.assertContains(r, "Foundations")
        self.assertNotContains(r, "Zed")

    def test_an_archived_sites_page_is_404(self):
        self.site.archive()
        self.login("editor")
        self.assertEqual(self.client.get(self.url("milestones")).status_code, 404)