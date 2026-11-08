from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import Site


class SignInTests(TestCase):
    def setUp(self):
        User.objects.create_user("a@example.com", "pw12345678", full_name="A")

    def test_sign_in_page_loads(self):
        self.assertEqual(self.client.get(reverse("signin")).status_code, 200)

    def test_good_credentials_reach_the_overview(self):
        r = self.client.post(
            reverse("signin"), {"username": "a@example.com", "password": "pw12345678"}
        )
        self.assertRedirects(r, reverse("overview"))

    def test_email_capitals_do_not_matter(self):
        r = self.client.post(
            reverse("signin"), {"username": "A@EXAMPLE.com", "password": "pw12345678"}
        )
        self.assertRedirects(r, reverse("overview"))

    def test_wrong_password_shows_an_error(self):
        r = self.client.post(
            reverse("signin"), {"username": "a@example.com", "password": "nope"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "don’t match")

    def test_overview_needs_sign_in(self):
        r = self.client.get(reverse("overview"))
        self.assertRedirects(r, "/signin/?next=/app/")

    def test_sign_out(self):
        self.client.login(username="a@example.com", password="pw12345678")
        r = self.client.post(reverse("signout"))
        self.assertRedirects(r, reverse("signin"))
        self.assertEqual(self.client.get(reverse("overview")).status_code, 302)


def make_site(org, name, status="planned"):
    return Site.objects.create(
        organisation=org, name=name, kind="road", status=status,
        location=Point(7.4, 9.07, srid=4326),
    )


class OverviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        Membership.objects.create(user=self.user, organisation=self.org, role="editor")
        self.client.login(username="a@example.com", password="pw12345678")

    def test_user_without_organisation_sees_welcome(self):
        other = User.objects.create_user("b@example.com", "pw12345678", full_name="B")
        self.client.login(username="b@example.com", password="pw12345678")
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "not part of an organisation")

    def test_only_own_organisation_sites_are_shown(self):
        make_site(self.org, "Mine One")
        stranger_org = Organisation.objects.create(name="Other", kind="private")
        make_site(stranger_org, "Not Mine")
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "Mine One")
        self.assertNotContains(r, "Not Mine")

    def test_status_counts(self):
        make_site(self.org, "A", "in_progress")
        make_site(self.org, "B", "in_progress")
        make_site(self.org, "C", "complete")
        counts = {
            s["key"]: s["count"]
            for s in self.client.get(reverse("overview")).context["status_counts"]
        }
        self.assertEqual(counts["in_progress"], 2)
        self.assertEqual(counts["complete"], 1)
        self.assertEqual(counts["planned"], 0)

    def test_delayed_and_stalled_need_attention(self):
        make_site(self.org, "Fine", "in_progress")
        make_site(self.org, "Late", "delayed")
        make_site(self.org, "Stuck", "stalled")
        r = self.client.get(reverse("overview"))
        self.assertEqual(r.context["attention_count"], 2)

    def test_unverified_organisation_sees_the_notice(self):
        self.org.verification = "pending"
        self.org.save()
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "Pending verification")
        
class SitesPageTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.editor = User.objects.create_user("e@example.com", "pw12345678", full_name="E")
        self.viewer = User.objects.create_user("v@example.com", "pw12345678", full_name="V")
        Membership.objects.create(user=self.editor, organisation=self.org, role="editor")
        Membership.objects.create(user=self.viewer, organisation=self.org, role="viewer")

    def login(self, who):
        self.client.login(username=f"{who}@example.com", password="pw12345678")

    def good_data(self, **extra):
        data = {
            "name": "New Road", "kind": "road", "status": "planned",
            "owner_name": "Works", "target_date": "", "progress": 10,
            "latitude": 9.07, "longitude": 7.4, "description": "",
        }
        data.update(extra)
        return data

    def test_list_needs_sign_in(self):
        self.assertEqual(self.client.get(reverse("sites")).status_code, 302)

    def test_list_shows_only_own_organisation_sites(self):
        make_site(self.org, "Mine One")
        make_site(Organisation.objects.create(name="Other", kind="private"), "Not Mine")
        self.login("e")
        r = self.client.get(reverse("sites"))
        self.assertContains(r, "Mine One")
        self.assertNotContains(r, "Not Mine")

    def test_status_filter_and_search(self):
        make_site(self.org, "Alpha Road", "delayed")
        make_site(self.org, "Beta Bridge", "planned")
        self.login("e")
        r = self.client.get(reverse("sites"), {"status": "delayed"})
        self.assertContains(r, "Alpha Road")
        self.assertNotContains(r, "Beta Bridge")
        r = self.client.get(reverse("sites"), {"q": "bridge"})
        self.assertContains(r, "Beta Bridge")
        self.assertNotContains(r, "Alpha Road")

    def test_editor_can_create_a_site(self):
        self.login("e")
        r = self.client.post(reverse("site_new"), self.good_data())
        self.assertRedirects(r, reverse("sites"))
        site = Site.objects.get(name="New Road")
        self.assertEqual(site.organisation, self.org)
        self.assertEqual((site.location.x, site.location.y), (7.4, 9.07))

    def test_viewer_cannot_create_a_site(self):
        self.login("v")
        self.assertEqual(self.client.get(reverse("site_new")).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("site_new"), self.good_data()).status_code, 403
        )
        self.assertFalse(Site.objects.filter(name="New Road").exists())

    def test_invalid_coordinates_are_rejected(self):
        self.login("e")
        r = self.client.post(reverse("site_new"), self.good_data(latitude=123))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Site.objects.filter(name="New Road").exists())

    def test_progress_over_100_is_rejected(self):
        self.login("e")
        r = self.client.post(reverse("site_new"), self.good_data(progress=150))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Site.objects.filter(name="New Road").exists())

    def test_edit_updates_the_site_and_its_location(self):
        site = make_site(self.org, "Old Name")
        self.login("e")
        r = self.client.post(
            reverse("site_edit", args=[site.pk]),
            self.good_data(name="New Name", latitude=10.5, longitude=8.5),
        )
        self.assertRedirects(r, reverse("sites"))
        site.refresh_from_db()
        self.assertEqual(site.name, "New Name")
        self.assertEqual((site.location.x, site.location.y), (8.5, 10.5))

    def test_cannot_edit_another_organisations_site(self):
        theirs = make_site(Organisation.objects.create(name="Other", kind="private"), "Theirs")
        self.login("e")
        r = self.client.post(reverse("site_edit", args=[theirs.pk]), self.good_data())
        self.assertEqual(r.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.name, "Theirs")