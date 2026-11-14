from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import Site

PW = "pw12345678"


def make_site(org, name):
    return Site.objects.create(
        organisation=org, name=name, kind="road",
        location=Point(7.4, 9.07, srid=4326),
    )


class OverviewEmptyStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a@example.com", PW, full_name="A")
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.membership = Membership.objects.create(
            user=self.user, organisation=self.org, role="editor"
        )
        self.client.login(username="a@example.com", password=PW)

    def get(self):
        return self.client.get(reverse("overview"))

    def test_no_sites_shows_add_first_site_for_editor(self):
        r = self.get()
        self.assertContains(r, "No sites yet")
        self.assertContains(r, "Add your first site")
        self.assertContains(r, reverse("site_new"))
        self.assertNotContains(r, "from the admin for now")

    def test_no_sites_viewer_is_told_to_ask_and_gets_no_link(self):
        self.membership.role = "viewer"
        self.membership.save()
        r = self.get()
        self.assertContains(r, "Ask an admin or editor")
        self.assertNotContains(r, "Add your first site")
        self.assertNotContains(r, reverse("site_new"))

    def test_other_organisations_sites_do_not_hide_the_empty_state(self):
        other = Organisation.objects.create(name="Other", kind="private")
        make_site(other, "Not Mine")
        r = self.get()
        self.assertContains(r, "No sites yet")
        self.assertNotContains(r, "Not Mine")

    def test_sites_without_evidence_show_the_notice(self):
        make_site(self.org, "Mine One")
        r = self.get()
        self.assertContains(r, "Nothing has been logged on any site yet")
        self.assertNotContains(r, "No sites yet")
        self.assertFalse(r.context["has_any_evidence"])

    def test_no_notice_when_there_are_no_sites(self):
        r = self.get()
        self.assertNotContains(r, "Nothing has been logged on any site yet")

    def test_can_add_site_flag_follows_role(self):
        self.assertTrue(self.get().context["can_add_site"])
        self.membership.role = "field"
        self.membership.save()
        self.assertFalse(self.get().context["can_add_site"])