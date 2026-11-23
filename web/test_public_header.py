from django.test import TestCase
from django.urls import reverse

from accounts.models import User

PAGES = ["home", "projects", "public_map", "how_it_works", "about", "contact"]


class PublicHeaderTests(TestCase):
    def test_public_pages_use_the_dashboard_bar_and_drawer(self):
        for name in PAGES:
            with self.subTest(page=name):
                r = self.client.get(reverse(name))
                self.assertContains(r, 'class="appbar"')
                self.assertContains(r, 'id="mobile-nav"')
                self.assertContains(r, "mobile-nav-backdrop")
                self.assertNotContains(r, 'class="pubbar"')

    def test_signed_out_header_offers_sign_in(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, 'class="btn btn-primary btn-small" href="%s"' % reverse("signin"))
        self.assertNotContains(r, "Open workspace")

    def test_signed_in_header_offers_the_workspace(self):
        User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        self.client.login(username="a@example.com", password="pw12345678")
        r = self.client.get(reverse("home"))
        self.assertContains(r, 'href="%s">Dashboard' % reverse("overview"))
        self.assertNotContains(r, "Agency sign in")

    def test_current_page_is_marked_in_bar_and_drawer(self):
        r = self.client.get(reverse("how_it_works"))
        self.assertContains(
            r, 'href="%s" aria-current="page"' % reverse("how_it_works"), count=2
        )

    def test_drawer_links_to_about_and_contact(self):
        r = self.client.get(reverse("home"))
        for name in ("about", "contact"):
            self.assertContains(r, 'href="%s"' % reverse(name))

    def test_dashboard_and_public_site_share_the_same_nav_markup(self):
        User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        self.client.login(username="a@example.com", password="pw12345678")
        for name in ("overview", "home"):
            with self.subTest(page=name):
                r = self.client.get(reverse(name))
                self.assertContains(r, '<nav class="mainnav desktop-nav"')
                self.assertContains(r, 'class="mainnav mobile-nav"')


class LinkWordingTests(TestCase):
    PUBLIC = ("home", "projects", "public_map", "about", "how_it_works", "contact")
    AUTH = ("signin", "signup", "password_reset")

    def test_sign_in_is_just_called_sign_in(self):
        for name in self.PUBLIC:
            with self.subTest(page=name):
                r = self.client.get(reverse(name))
                self.assertContains(r, ">Sign in</a>")
                self.assertNotContains(r, "Agency sign in")

    def test_signed_in_visitors_see_dashboard_not_workspace(self):
        User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        self.client.login(username="a@example.com", password="pw12345678")
        for name in self.PUBLIC:
            with self.subTest(page=name):
                r = self.client.get(reverse(name))
                self.assertContains(r, ">Dashboard</a>")
                for old in ("Open workspace", "Open dashboard", "Agency sign in"):
                    self.assertNotContains(r, old)

    def test_no_arrow_characters_in_page_markup(self):
        for name in self.PUBLIC + self.AUTH:
            with self.subTest(page=name):
                r = self.client.get(reverse(name))
                self.assertNotContains(r, "\u2192")
                self.assertNotContains(r, "\u2190")
        User.objects.create_user("b@example.com", "pw12345678", full_name="B")
        self.client.login(username="b@example.com", password="pw12345678")
        for name in ("overview", "settings_hub"):
            with self.subTest(page=name):
                r = self.client.get(reverse(name))
                self.assertNotContains(r, "\u2192")
                self.assertNotContains(r, "\u2190")
