from django.test import TestCase
from django.urls import reverse

from accounts.models import User


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