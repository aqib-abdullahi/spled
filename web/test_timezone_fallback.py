from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

GOOD = "s3cure-Passw0rd!"


class BadStoredZoneTests(TestCase):
    def test_no_stored_zone_can_break_a_page(self):
        user = User.objects.create_user("a@example.com", GOOD, full_name="Ada")
        self.client.login(username="a@example.com", password=GOOD)
        for name in ("Nowhere/Land", "../../etc/passwd", "UTC+5", "x" * 64, "Europe/", "/", " "):
            User.objects.filter(pk=user.pk).update(time_zone=name)
            for url in (reverse("overview"), reverse("profile"), reverse("sites")):
                with self.subTest(zone=name, url=url):
                    response = self.client.get(url)
                    self.assertLess(response.status_code, 400)
                    self.assertEqual(timezone.get_current_timezone_name(), "Africa/Lagos")
