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


import re  # noqa: E402
from pathlib import Path  # noqa: E402

from django.conf import settings  # noqa: E402

from organisations.models import Membership, Organisation  # noqa: E402

FA_DIR = Path(settings.BASE_DIR) / "static" / "vendor" / "fontawesome"


def icon_classes(html):
    found = set()
    for tag in re.findall(r"<i\b[^>]*>", html):
        match = re.search(r'class="([^"]*)"', tag)
        if match and "fa-" in match.group(1):
            found.add(match.group(1))
    return found


class IconTests(TestCase):
    PUBLIC = ("home", "projects", "public_map", "about", "how_it_works", "contact")
    APP = ("overview", "settings_hub", "staff_map")

    def pages(self):
        """Rendered HTML of public pages, then app pages as an admin."""
        html = [self.client.get(reverse(name)).content.decode() for name in self.PUBLIC]
        user = User.objects.create_user("icons@example.com", "pw12345678", full_name="I")
        org = Organisation.objects.create(name="Icons", kind="government", verification="verified")
        Membership.objects.create(user=user, organisation=org, role="admin")
        self.client.login(username="icons@example.com", password="pw12345678")
        html += [self.client.get(reverse(name)).content.decode() for name in self.APP]
        return html

    def test_font_awesome_replaces_lucide_everywhere(self):
        for page in self.pages():
            self.assertNotIn("data-lucide", page)
            self.assertNotIn("lucide", page)
            self.assertIn("vendor/fontawesome/css/all.min.css", page)

    def test_every_icon_uses_the_solid_style(self):
        for page in self.pages():
            for classes in icon_classes(page):
                with self.subTest(classes=classes):
                    self.assertIn("fa-solid", classes.split())

    def test_every_icon_exists_in_the_vendored_stylesheet(self):
        css = (FA_DIR / "css" / "all.min.css").read_text(encoding="utf-8", errors="replace")
        for page in self.pages():
            for classes in icon_classes(page):
                for name in classes.split():
                    if name.startswith("fa-") and name not in ("fa-solid", "fa-fw"):
                        with self.subTest(icon=name):
                            self.assertIsNotNone(re.search(r"\." + re.escape(name) + r"(?![a-z0-9-])", css))

    def test_pages_actually_use_icons(self):
        pages = self.pages()
        self.assertGreater(len(icon_classes(pages[0])), 3)    # the landing page
        self.assertGreater(len(icon_classes(pages[-3])), 6)   # the dashboard overview

    def test_the_font_files_are_in_the_project(self):
        self.assertTrue((FA_DIR / "webfonts" / "fa-solid-900.woff2").is_file())
        css = (FA_DIR / "css" / "all.min.css").read_text(encoding="utf-8", errors="replace")
        self.assertIn("fa-solid-900", css)
