from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, Site


def make_site(org, name, **kwargs):
    return Site.objects.create(
        organisation=org, name=name, kind="road",
        location=Point(7.4, 9.07, srid=4326), **kwargs,
    )


class PublicPortalTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Works Dept", kind="government", verification="verified"
        )
        self.staff = User.objects.create_user(
            "secret.person@example.com", "pw12345678", full_name="Secret Person"
        )
        Membership.objects.create(user=self.staff, organisation=self.org, role="editor")
        self.public = make_site(self.org, "Public Road", is_public=True)

    def test_pages_open_without_signing_in(self):
        for url in (
            reverse("home"),
            reverse("projects"),
            reverse("project", args=[self.public.pk]),
        ):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_only_published_sites_are_listed(self):
        make_site(self.org, "Private Road")
        r = self.client.get(reverse("projects"))
        self.assertContains(r, "Public Road")
        self.assertNotContains(r, "Private Road")

    def test_unverified_organisations_are_never_shown(self):
        pending = Organisation.objects.create(name="New Co", kind="private")
        hidden = make_site(pending, "Hidden Build", is_public=True)
        self.assertNotContains(self.client.get(reverse("projects")), "Hidden Build")
        self.assertEqual(
            self.client.get(reverse("project", args=[hidden.pk])).status_code, 404
        )

    def test_private_and_archived_projects_return_404(self):
        private = make_site(self.org, "Private Road")
        archived = make_site(self.org, "Old Road", is_public=True)
        archived.archive()
        for site in (private, archived):
            self.assertEqual(
                self.client.get(reverse("project", args=[site.pk])).status_code, 404
            )

    def test_staff_names_and_emails_never_appear(self):
        EvidenceEntry.objects.create(
            site=self.public, author=self.staff, kind="note", body="Poured foundations",
            location=Point(7.4001, 9.0701, srid=4326),
        )
        for url in (reverse("projects"), reverse("project", args=[self.public.pk])):
            r = self.client.get(url)
            self.assertNotContains(r, "Secret Person")
            self.assertNotContains(r, "secret.person@example.com")

    def test_project_page_shows_verified_evidence(self):
        EvidenceEntry.objects.create(
            site=self.public, author=self.staff, kind="note", body="Poured foundations",
            location=Point(7.4001, 9.0701, srid=4326),
        )
        r = self.client.get(reverse("project", args=[self.public.pk]))
        self.assertContains(r, "Poured foundations")
        self.assertContains(r, "Verified on site")

    def test_status_filter_and_search(self):
        make_site(self.org, "Bridge Works", is_public=True, status="delayed")
        r = self.client.get(reverse("projects"), {"status": "delayed"})
        self.assertContains(r, "Bridge Works")
        self.assertNotContains(r, "Public Road")
        r = self.client.get(reverse("projects"), {"q": "bridge"})
        self.assertContains(r, "Bridge Works")
        self.assertNotContains(r, "Public Road")

    def test_signed_in_users_see_the_same_public_view(self):
        make_site(self.org, "Private Road")
        self.client.login(username="secret.person@example.com", password="pw12345678")
        self.assertNotContains(self.client.get(reverse("projects")), "Private Road")