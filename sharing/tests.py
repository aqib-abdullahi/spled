from datetime import timedelta

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from organisations.models import Organisation
from registry.models import Site

from .models import MAX_FAILED, ShareLink


class ShareLinkModelTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Org", kind="government")
        self.user = User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        self.site = Site.objects.create(
            organisation=self.org, name="S", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )

    def make(self, **kwargs):
        kwargs.setdefault("label", "Investors")
        return ShareLink.create_for(self.site, created_by=self.user, **kwargs)

    def test_only_a_hash_of_the_token_is_stored(self):
        link, raw = self.make()
        self.assertEqual(link.token_hash, ShareLink.hash_token(raw))
        self.assertNotEqual(link.token_hash, raw)
        self.assertGreaterEqual(len(raw), 40)

    def test_lookup_finds_the_link_and_ignores_unknown_tokens(self):
        link, raw = self.make()
        self.assertEqual(ShareLink.lookup(raw), link)
        self.assertIsNone(ShareLink.lookup("nope"))
        self.assertIsNone(ShareLink.lookup(""))

    def test_expiry_is_set_from_the_chosen_days(self):
        link, _ = self.make(days=7)
        expected = timezone.now() + timedelta(days=7)
        self.assertLess(abs(link.expires_at - expected), timedelta(minutes=1))

    def test_state_follows_expiry_revocation_and_archiving(self):
        link, _ = self.make()
        self.assertEqual(link.state, "active")
        link.expires_at = timezone.now() - timedelta(minutes=1)
        self.assertEqual(link.state, "expired")
        link.expires_at = timezone.now() + timedelta(days=1)
        link.revoked_at = timezone.now()
        self.assertEqual(link.state, "revoked")
        link.revoked_at = None
        self.site.archive()
        self.assertEqual(link.state, "unavailable")

    def test_the_password_is_stored_hashed_and_checked(self):
        link, _ = self.make(password="correct horse")
        self.assertTrue(link.has_password)
        self.assertNotEqual(link.password_hash, "correct horse")
        self.assertEqual(link.try_password("correct horse"), "ok")
        self.assertEqual(link.try_password("wrong"), "wrong")

    def test_no_password_means_not_protected(self):
        link, _ = self.make()
        self.assertFalse(link.has_password)

    def test_wrong_passwords_lock_the_link_after_the_limit(self):
        link, _ = self.make(password="correct horse")
        for _ in range(MAX_FAILED - 1):
            self.assertEqual(link.try_password("nope"), "wrong")
        self.assertEqual(link.try_password("nope"), "locked")
        self.assertTrue(link.is_locked)
        self.assertEqual(link.try_password("correct horse"), "locked")

    def test_a_correct_password_resets_the_failure_count(self):
        link, _ = self.make(password="correct horse")
        for _ in range(3):
            link.try_password("nope")
        self.assertEqual(link.failed_attempts, 3)
        self.assertEqual(link.try_password("correct horse"), "ok")
        self.assertEqual(link.failed_attempts, 0)

    def test_a_lock_expires(self):
        link, _ = self.make(password="correct horse")
        for _ in range(MAX_FAILED):
            link.try_password("nope")
        self.assertTrue(link.is_locked)
        ShareLink.objects.filter(pk=link.pk).update(
            locked_until=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(link.try_password("correct horse"), "ok")
        self.assertFalse(link.is_locked)

    def test_views_are_counted(self):
        link, _ = self.make()
        link.record_view()
        link.record_view()
        link.refresh_from_db()
        self.assertEqual(link.view_count, 2)
        self.assertIsNotNone(link.last_viewed_at)