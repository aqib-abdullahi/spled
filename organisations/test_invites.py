from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User

from .models import Invitation, Membership, Organisation
from .team import LastAdminError, change_role, remove_member


class InvitationTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Org", kind="government", verification="verified"
        )
        self.admin = User.objects.create_user(
            "admin@example.com", "pw12345678", full_name="Admin"
        )
        Membership.objects.create(user=self.admin, organisation=self.org, role="admin")
        self.newbie = User.objects.create_user(
            "new@example.com", "pw12345678", full_name="New"
        )

    def invite(self, email="new@example.com", role="editor"):
        return Invitation.create_for(self.org, email, role, self.admin)

    def test_only_a_hash_of_the_token_is_stored(self):
        inv, raw = self.invite()
        self.assertEqual(inv.token_hash, Invitation.hash_token(raw))
        self.assertNotEqual(inv.token_hash, raw)
        self.assertEqual(Invitation.lookup(raw), inv)
        self.assertIsNone(Invitation.lookup("not-a-real-token"))

    def test_email_is_lowercased(self):
        inv, _ = self.invite("New@Example.COM")
        self.assertEqual(inv.email, "new@example.com")

    def test_states(self):
        inv, _ = self.invite()
        self.assertEqual(inv.state, "pending")
        inv.expires_at = timezone.now() - timedelta(minutes=1)
        self.assertEqual(inv.state, "expired")
        inv.expires_at = timezone.now() + timedelta(days=1)
        inv.revoked_at = timezone.now()
        self.assertEqual(inv.state, "revoked")
        inv.revoked_at = None
        inv.accepted_at = timezone.now()
        self.assertEqual(inv.state, "accepted")

    def test_accept_creates_the_membership(self):
        inv, _ = self.invite(role="field")
        inv.accept(self.newbie)
        m = Membership.objects.get(user=self.newbie, organisation=self.org)
        self.assertEqual(m.role, "field")
        inv.refresh_from_db()
        self.assertIsNotNone(inv.accepted_at)

    def test_accept_refuses_a_different_email(self):
        inv, _ = self.invite()
        other = User.objects.create_user(
            "other@example.com", "pw12345678", full_name="O"
        )
        with self.assertRaises(ValueError):
            inv.accept(other)
        self.assertFalse(Membership.objects.filter(user=other).exists())

    def test_accept_refuses_expired_revoked_or_used(self):
        for change in ("expired", "revoked", "used"):
            inv, _ = self.invite(f"{change}@example.com")
            user = User.objects.create_user(
                f"{change}@example.com", "pw12345678", full_name=change
            )
            if change == "expired":
                inv.expires_at = timezone.now() - timedelta(minutes=1)
            elif change == "revoked":
                inv.revoked_at = timezone.now()
            else:
                inv.accepted_at = timezone.now()
            with self.assertRaises(ValueError):
                inv.accept(user)
            self.assertFalse(Membership.objects.filter(user=user).exists())

    def test_one_open_invite_per_email(self):
        inv, _ = self.invite()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Invitation.create_for(self.org, "new@example.com", "viewer", self.admin)
        inv.revoked_at = timezone.now()
        inv.save()
        again, _ = Invitation.create_for(
            self.org, "new@example.com", "viewer", self.admin
        )
        self.assertEqual(again.state, "pending")

    def test_expired_invite_is_replaced(self):
        old, _ = self.invite()
        Invitation.objects.filter(pk=old.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        fresh, _ = self.invite(role="viewer")
        old.refresh_from_db()
        self.assertIsNotNone(old.revoked_at)
        self.assertEqual(fresh.state, "pending")


class TeamHelperTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Org", kind="government")
        self.a1 = User.objects.create_user("a1@example.com", "pw12345678", full_name="A1")
        self.a2 = User.objects.create_user("a2@example.com", "pw12345678", full_name="A2")
        self.m1 = Membership.objects.create(user=self.a1, organisation=self.org, role="admin")

    def test_last_admin_cannot_be_demoted(self):
        with self.assertRaises(LastAdminError):
            change_role(self.m1, "viewer")
        self.m1.refresh_from_db()
        self.assertEqual(self.m1.role, "admin")

    def test_last_admin_cannot_be_removed(self):
        with self.assertRaises(LastAdminError):
            remove_member(self.m1)
        self.assertTrue(Membership.objects.filter(pk=self.m1.pk).exists())

    def test_admin_can_change_when_another_admin_exists(self):
        m2 = Membership.objects.create(user=self.a2, organisation=self.org, role="admin")
        old = change_role(self.m1, "editor")
        self.assertEqual(old, "admin")
        self.assertEqual(self.m1.role, "editor")
        with self.assertRaises(LastAdminError):
            remove_member(m2)
        remove_member(self.m1)
        self.assertFalse(Membership.objects.filter(pk=self.m1.pk).exists())

    def test_unknown_role_is_refused(self):
        with self.assertRaises(ValueError):
            change_role(self.m1, "boss")