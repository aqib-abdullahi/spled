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