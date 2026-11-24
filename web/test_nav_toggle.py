from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class NavToggleOrderTests(TestCase):
    """The menu button sits on the right, so it must come last for keyboard users too."""

    def assert_toggle_after_brand(self, response):
        html = response.content.decode()
        self.assertGreater(html.index('class="nav-toggle"'), html.index('class="brand"'))

    def test_public_site_menu_button_comes_after_the_brand(self):
        self.assert_toggle_after_brand(self.client.get(reverse("home")))

    def test_dashboard_menu_button_comes_after_the_brand(self):
        User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        self.client.login(username="a@example.com", password="pw12345678")
        self.assert_toggle_after_brand(self.client.get(reverse("overview")))


import re  # noqa: E402
from pathlib import Path  # noqa: E402

from django.conf import settings  # noqa: E402

from organisations.models import Membership, Organisation  # noqa: E402

SPLED_CSS = Path(settings.BASE_DIR) / "static" / "css" / "spled.css"


def sidebar_of(response):
    html = response.content.decode()
    start = html.index('<aside class="sidebar"')
    return html[start:html.index("</aside>", start)]


class SidebarTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("side@example.com", "pw12345678", full_name="Side Person")
        self.org = Organisation.objects.create(name="Side Org", kind="government", verification="verified")
        self.membership = Membership.objects.create(user=self.user, organisation=self.org, role="admin")
        self.client.login(username="side@example.com", password="pw12345678")

    def sidebar(self, role, page="overview"):
        self.membership.role = role
        self.membership.save()
        return sidebar_of(self.client.get(reverse(page)))

    def links(self, html):
        return set(re.findall(r'href="([^"]+)"', html))

    def test_an_admin_sees_every_link(self):
        found = self.links(self.sidebar("admin"))
        for name in ("overview", "sites", "staff_map", "review", "reports", "team",
                     "audit_log", "org_settings", "settings_hub", "profile"):
            with self.subTest(link=name):
                self.assertIn(reverse(name), found)

    def test_a_viewer_sees_only_what_a_viewer_may_use(self):
        found = self.links(self.sidebar("viewer"))
        for name in ("overview", "sites", "staff_map", "settings_hub", "profile"):
            self.assertIn(reverse(name), found)
        for name in ("review", "reports", "team", "audit_log", "org_settings"):
            with self.subTest(hidden=name):
                self.assertNotIn(reverse(name), found)

    def test_an_editor_reviews_and_reports_but_does_not_manage(self):
        found = self.links(self.sidebar("editor"))
        self.assertIn(reverse("review"), found)
        self.assertIn(reverse("reports"), found)
        for name in ("team", "audit_log", "org_settings"):
            with self.subTest(hidden=name):
                self.assertNotIn(reverse(name), found)

    def test_the_current_page_is_marked(self):
        html = self.sidebar("editor", page="sites")
        self.assertIn('href="%s" aria-current="page"' % reverse("sites"), html)
        self.assertNotIn('href="%s" aria-current="page"' % reverse("overview"), html)

    def test_it_shows_who_is_signed_in_and_can_sign_out(self):
        html = self.sidebar("viewer")
        self.assertIn("Side Person", html)
        self.assertIn("side@example.com", html)
        self.assertIn('action="%s"' % reverse("signout"), html)
        self.assertIn("csrfmiddlewaretoken", html)

    def test_public_and_sign_in_pages_have_no_sidebar(self):
        self.client.logout()
        for name in ("home", "projects", "signin", "signup"):
            with self.subTest(page=name):
                self.assertNotContains(self.client.get(reverse(name)), 'class="sidebar"')

    def test_the_panel_replaces_the_top_bar_only_from_1024px(self):
        css = SPLED_CSS.read_text(encoding="utf-8")
        block = css[css.index("Step 62"):]
        self.assertIn(".sidebar { display: none; }", block)
        self.assertIn("@media (min-width: 1024px)", block)
        self.assertIn(".app-main > .appbar { display: none; }", block)
        self.assertIn("@container (min-width: 720px)", block)
        self.assertIn("@media print", block)

    def test_card_pages_ask_for_the_two_column_layout(self):
        self.membership.role = "admin"
        self.membership.save()
        for name in ("team", "reports", "profile"):
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name)), 'class="page page-cols"')


from django.contrib.gis.geos import Point  # noqa: E402

from registry.models import Site  # noqa: E402
from registry.photos import MAX_BYTES, MAX_PHOTOS  # noqa: E402


class PageLayoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("lay@example.com", "pw12345678", full_name="Lay")
        self.org = Organisation.objects.create(name="Lay Org", kind="government", verification="verified")
        Membership.objects.create(user=self.user, organisation=self.org, role="admin")
        self.site = Site.objects.create(
            organisation=self.org, name="Lay Road", kind="road", location=Point(7.4, 9.07, srid=4326)
        )
        self.client.login(username="lay@example.com", password="pw12345678")

    def css(self):
        text = SPLED_CSS.read_text(encoding="utf-8")
        return text[text.index("Step 64"):]

    def test_pages_ask_for_their_layouts(self):
        expected = [
            ("org_settings", (), "page-org"),
            ("review", (), "page-grid"),
            ("share_links", (self.site.pk,), "page-share"),
            ("milestones", (self.site.pk,), "page-ms"),
        ]
        for name, args, cls in expected:
            with self.subTest(page=name):
                self.assertContains(self.client.get(reverse(name, args=args)), 'class="page %s"' % cls)

    def test_security_panels_sit_side_by_side_in_css(self):
        self.assertIn('section[aria-label="Two-step verification"].stack', self.css())

    def test_team_layout_no_longer_depends_on_row_numbers(self):
        text = SPLED_CSS.read_text(encoding="utf-8")
        self.assertNotIn("grid-row: 2 / span 3", text)
        self.assertIn(".page-cols { grid-auto-flow: dense; }", text)

    def test_milestones_use_two_columns_only_when_there_is_a_second_column(self):
        self.assertIn(':has(> section[aria-label="Add a milestone"])', self.css())

    def test_site_form_puts_the_map_beside_the_fields(self):
        html = self.client.get(reverse("site_new")).content.decode()
        self.assertEqual(html.count('class="site-form-grid"'), 1)
        self.assertEqual(html.count('id="pin-map"'), 1)
        self.assertLess(html.index("site-fields"), html.index('id="pin-map"'))
        self.assertIn("Save site", html)

    def test_evidence_form_shows_the_site_beside_the_form(self):
        r = self.client.get(reverse("evidence_new", args=[self.site.pk]))
        self.assertContains(r, 'class="evidence-layout"')
        self.assertContains(r, 'aria-label="About this site"')
        self.assertContains(r, "Lay Road")
        self.assertContains(r, "Save entry")
        self.assertContains(r, "Use my current location")

    def test_photo_limits_given_to_the_validation_script_match_the_server(self):
        r = self.client.get(reverse("evidence_new", args=[self.site.pk]))
        self.assertContains(r, 'setAttribute("data-max-files", "%d")' % MAX_PHOTOS)
        self.assertContains(r, 'setAttribute("data-max-bytes", "%d")' % MAX_BYTES)
