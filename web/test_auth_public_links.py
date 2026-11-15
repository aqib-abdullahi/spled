from django.test import TestCase
from django.urls import reverse

from accounts.models import User

PW = "pw12345678"
LINK = 'class="auth-public-link" href="%s"'


class AuthPagesLinkToThePublicSiteTests(TestCase):
    def test_sign_in_has_a_link_to_the_public_site(self):
        r = self.client.get(reverse("signin"))
        self.assertContains(r, LINK % reverse("home"))

    def test_create_account_has_it_and_no_extra_explore_link(self):
        r = self.client.get(reverse("signup"))
        self.assertContains(r, LINK % reverse("home"))
        self.assertNotContains(r, "Explore public projects")

    def test_pages_using_the_shared_layout_have_it_too(self):
        # password_reset_form extends auth_base.html
        r = self.client.get(reverse("password_reset"))
        self.assertContains(r, LINK % reverse("home"))

    def test_sign_in_keeps_its_original_look(self):
        r = self.client.get(reverse("signin"))
        self.assertContains(r, 'class="brand"', count=1)
        self.assertContains(r, 'class="split-side"', count=1)
        self.assertContains(r, "09.0765° N · 7.3986° E")
        self.assertNotContains(r, 'class="appbar"')
        self.assertNotContains(r, "auth-bar-link")
        self.assertNotContains(r, "auth-back")

    def test_after_signing_out_the_public_site_is_one_click_away(self):
        User.objects.create_user("a@example.com", PW, full_name="A")
        self.client.login(username="a@example.com", password=PW)
        r = self.client.post(reverse("signout"), follow=True)
        self.assertRedirects(r, reverse("signin"))
        self.assertContains(r, LINK % reverse("home"))