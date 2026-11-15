from django.test import TestCase
from django.urls import reverse

from accounts.models import User

PW = "pw12345678"
BACK = 'class="auth-back" href="%s"'


class AuthPagesLinkToThePublicSiteTests(TestCase):
    def test_sign_in_page_has_the_back_link(self):
        r = self.client.get(reverse("signin"))
        self.assertContains(r, BACK % reverse("home"))

    def test_create_account_page_has_the_back_link(self):
        r = self.client.get(reverse("signup"))
        self.assertContains(r, BACK % reverse("home"))

    def test_pages_using_the_shared_auth_layout_have_it_too(self):
        # password_reset_form extends auth_base.html
        r = self.client.get(reverse("password_reset"))
        self.assertContains(r, BACK % reverse("home"))

    def test_sign_in_and_create_account_offer_public_projects(self):
        for name in ("signin", "signup"):
            with self.subTest(page=name):
                r = self.client.get(reverse(name))
                self.assertContains(r, "Explore public projects")
                self.assertContains(r, 'href="%s"' % reverse("projects"))

    def test_after_signing_out_the_public_site_is_one_click_away(self):
        User.objects.create_user("a@example.com", PW, full_name="A")
        self.client.login(username="a@example.com", password=PW)
        r = self.client.post(reverse("signout"), follow=True)
        self.assertRedirects(r, reverse("signin"))
        self.assertContains(r, BACK % reverse("home"))