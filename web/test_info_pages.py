from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings
from django.urls import reverse

from organisations.models import Organisation
from registry.models import VERIFY_RADIUS_M, Site

INFO = ["how_it_works", "about", "contact", "privacy", "terms"]


class InfoPageTests(TestCase):
    def get(self, name):
        return self.client.get(reverse(name))

    def test_all_pages_load_signed_out(self):
        for name in INFO:
            with self.subTest(page=name):
                self.assertEqual(self.get(name).status_code, 200)

    def test_every_page_has_a_meta_description(self):
        for name in ["home"] + INFO:
            with self.subTest(page=name):
                self.assertContains(self.get(name), '<meta name="description"')

    def test_public_nav_links_to_how_evidence_works(self):
        r = self.get("home")
        self.assertContains(r, 'href="%s"' % reverse("how_it_works"))
        self.assertNotContains(r, 'aria-disabled="true"')

    def test_footer_links_on_public_pages(self):
        for page in ("home", "projects", "public_map"):
            r = self.get(page)
            self.assertContains(r, 'class="sitefoot"')
            for name in ("about", "contact", "privacy", "terms", "how_it_works"):
                with self.subTest(page=page, link=name):
                    self.assertContains(r, 'href="%s"' % reverse(name))

    def test_how_page_uses_the_real_verify_radius(self):
        self.assertContains(self.get("how_it_works"), "%d metres" % VERIFY_RADIUS_M)

    @override_settings(CONTACT_EMAIL="")
    def test_contact_without_address_shows_no_mailto(self):
        r = self.get("contact")
        self.assertContains(r, "Contact details have not been set up yet.")
        self.assertNotContains(r, "mailto:")

    @override_settings(CONTACT_EMAIL="hello@example.com")
    def test_contact_with_address_shows_mailto(self):
        r = self.get("contact")
        self.assertContains(r, 'href="mailto:hello@example.com"')
        self.assertNotContains(r, "have not been set up yet")

    def test_privacy_and_terms_are_marked_as_drafts(self):
        for name in ("privacy", "terms"):
            with self.subTest(page=name):
                self.assertContains(self.get(name), "has not yet been reviewed by a lawyer")

    def test_privacy_names_the_outside_services(self):
        r = self.get("privacy")
        self.assertContains(r, "Google Fonts")
        self.assertContains(r, "OpenStreetMap")

    def test_home_has_no_made_up_numbers(self):
        r = self.get("home")
        for text in ("Watermain upgrade", "Drainage upgrade", "Access road works", "72%"):
            self.assertNotContains(r, text)

    def test_home_empty_state_messages(self):
        r = self.get("home")
        self.assertContains(r, "No projects have been published yet.", count=2)

    def test_home_panel_lists_a_published_project(self):
        org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        site = Site.objects.create(
            organisation=org, name="Real Road", kind="road", is_public=True,
            location=Point(7.4, 9.07, srid=4326),
        )
        r = self.get("home")
        self.assertContains(r, "Real Road")
        self.assertContains(r, 'class="panel-row" href="%s"' % reverse("project", args=[site.pk]))
        self.assertNotContains(r, "No projects have been published yet.")