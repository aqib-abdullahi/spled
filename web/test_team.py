import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from organisations.models import Invitation, Membership, Organisation

GOOD_PASSWORD = "s3cure-Passw0rd!"


class TeamTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ("admin", "editor", "field"):
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=role.title()
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user

    def login(self, role):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def member(self, role):
        return Membership.objects.get(user=self.users[role], organisation=self.org)

    def invite(self, email="new@example.com", role="editor"):
        self.login("admin")
        return self.client.post(reverse("invite_create"), {"email": email, "role": role})

    def make_invite(self, email="new@example.com", role="editor"):
        return Invitation.create_for(self.org, email, role, self.users["admin"])

    def actions(self):
        return list(AuditEvent.objects.order_by("id").values_list("action", flat=True))

    def test_team_page_is_for_admins_only(self):
        self.assertEqual(self.client.get(reverse("team")).status_code, 302)
        for role in ("editor", "field"):
            self.login(role)
            self.assertEqual(self.client.get(reverse("team")).status_code, 403, role)
        self.login("admin")
        r = self.client.get(reverse("team"))
        self.assertContains(r, "Invite someone")

    def test_invite_creates_the_invitation_email_and_audit_event(self):
        r = self.invite()
        self.assertRedirects(r, reverse("team"))
        inv = Invitation.objects.get()
        self.assertEqual(inv.email, "new@example.com")
        self.assertEqual(inv.role, "editor")
        self.assertEqual(inv.invited_by, self.users["admin"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["new@example.com"])
        token = re.search(r"/invite/([\w-]+)/", mail.outbox[0].body).group(1)
        self.assertEqual(Invitation.lookup(token), inv)
        self.assertEqual(self.actions(), ["member.invited"])

    def test_inviting_a_current_member_is_refused(self):
        r = self.invite("editor@example.com")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Invitation.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_inviting_twice_is_refused(self):
        self.invite()
        r = self.invite()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Invitation.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_bad_email_is_refused(self):
        r = self.invite("not-an-email")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_non_admins_cannot_change_the_team(self):
        inv, _ = self.make_invite()
        target = self.member("field")
        calls = [
            (reverse("invite_create"), {"email": "x@example.com", "role": "viewer"}),
            (reverse("invite_revoke", args=[inv.pk]), {}),
            (reverse("member_role", args=[target.pk]), {"role": "admin"}),
            (reverse("member_remove", args=[target.pk]), {}),
        ]
        for role in ("editor", "field"):
            self.login(role)
            for url, data in calls:
                self.assertEqual(
                    self.client.post(url, data).status_code, 403, (role, url)
                )
        self.assertEqual(Membership.objects.count(), 3)
        self.assertEqual(Invitation.objects.count(), 1)
        inv.refresh_from_db()
        self.assertIsNone(inv.revoked_at)
        self.assertEqual(self.member("field").role, "field")

    def test_revoking_an_invitation(self):
        inv, _ = self.make_invite()
        self.login("admin")
        url = reverse("invite_revoke", args=[inv.pk])
        self.assertRedirects(self.client.post(url), reverse("team"))
        inv.refresh_from_db()
        self.assertIsNotNone(inv.revoked_at)
        self.assertIn("invite.revoked", self.actions())
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_changing_a_role_is_saved_and_logged(self):
        self.login("admin")
        target = self.member("field")
        r = self.client.post(reverse("member_role", args=[target.pk]), {"role": "editor"})
        self.assertRedirects(r, reverse("team"))
        target.refresh_from_db()
        self.assertEqual(target.role, "editor")
        event = AuditEvent.objects.get(action="member.role_changed")
        self.assertEqual(event.detail["from"], "field")
        self.assertEqual(event.detail["to"], "editor")

    def test_the_last_admin_cannot_be_demoted(self):
        self.login("admin")
        target = self.member("admin")
        self.client.post(reverse("member_role", args=[target.pk]), {"role": "viewer"})
        target.refresh_from_db()
        self.assertEqual(target.role, "admin")
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_removing_a_member_is_saved_and_logged(self):
        self.login("admin")
        target = self.member("field")
        r = self.client.post(reverse("member_remove", args=[target.pk]))
        self.assertRedirects(r, reverse("team"))
        self.assertFalse(Membership.objects.filter(pk=target.pk).exists())
        self.assertIn("member.removed", self.actions())

    def test_the_last_admin_cannot_be_removed(self):
        self.login("admin")
        target = self.member("admin")
        self.client.post(reverse("member_remove", args=[target.pk]))
        self.assertTrue(Membership.objects.filter(pk=target.pk).exists())

    def test_other_organisations_members_cannot_be_touched(self):
        other_org = Organisation.objects.create(name="Other", kind="private")
        stranger = User.objects.create_user("s@example.com", "pw12345678", full_name="S")
        theirs = Membership.objects.create(user=stranger, organisation=other_org, role="admin")
        self.login("admin")
        self.assertEqual(
            self.client.post(reverse("member_role", args=[theirs.pk]), {"role": "viewer"}).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse("member_remove", args=[theirs.pk])).status_code, 404
        )
        theirs.refresh_from_db()
        self.assertEqual(theirs.role, "admin")

    def test_a_new_person_can_accept_and_is_signed_in(self):
        inv, raw = self.make_invite()
        url = reverse("invite_accept", args=[raw])
        self.assertContains(self.client.get(url), "Join Mine")
        r = self.client.post(url, {"full_name": "New Person", "password1": GOOD_PASSWORD})
        self.assertRedirects(r, reverse("overview"))
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.full_name, "New Person")
        self.assertEqual(
            Membership.objects.get(user=user, organisation=self.org).role, "editor"
        )
        inv.refresh_from_db()
        self.assertIsNotNone(inv.accepted_at)
        self.assertEqual(self.client.get(reverse("overview")).status_code, 200)
        self.assertEqual(self.client.session["org_id"], self.org.pk)
        self.assertIn("member.joined", self.actions())

    def test_a_weak_password_is_refused(self):
        _, raw = self.make_invite()
        r = self.client.post(
            reverse("invite_accept", args=[raw]),
            {"full_name": "New Person", "password1": "abc"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_an_expired_link_is_refused(self):
        inv, raw = self.make_invite()
        Invitation.objects.filter(pk=inv.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        url = reverse("invite_accept", args=[raw])
        self.assertContains(self.client.get(url), "expired")
        self.client.post(url, {"full_name": "New Person", "password1": GOOD_PASSWORD})
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_an_unknown_link_is_404(self):
        self.assertEqual(
            self.client.get(reverse("invite_accept", args=["nope"])).status_code, 404
        )

    def test_an_existing_user_is_asked_to_sign_in(self):
        User.objects.create_user("new@example.com", "pw12345678", full_name="Existing")
        _, raw = self.make_invite()
        url = reverse("invite_accept", args=[raw])
        r = self.client.get(url)
        self.assertContains(r, "Sign in to accept")
        self.assertContains(r, reverse("signin"))
        self.client.post(url, {"full_name": "X", "password1": GOOD_PASSWORD})
        self.assertFalse(
            Membership.objects.filter(user__email="new@example.com").exists()
        )

    def test_a_signed_in_matching_user_can_accept(self):
        user = User.objects.create_user("new@example.com", "pw12345678", full_name="Existing")
        _, raw = self.make_invite()
        self.client.login(username="new@example.com", password="pw12345678")
        url = reverse("invite_accept", args=[raw])
        self.assertContains(self.client.get(url), "Accept invitation")
        self.assertRedirects(self.client.post(url), reverse("overview"))
        self.assertEqual(
            Membership.objects.get(user=user, organisation=self.org).role, "editor"
        )

    def test_a_signed_in_user_with_another_email_is_refused(self):
        _, raw = self.make_invite()
        self.login("editor")
        url = reverse("invite_accept", args=[raw])
        self.assertContains(self.client.get(url), "different email address")
        self.client.post(url)
        self.assertEqual(Membership.objects.count(), 3)

    def test_a_used_link_cannot_be_reused(self):
        _, raw = self.make_invite()
        url = reverse("invite_accept", args=[raw])
        self.client.post(url, {"full_name": "New Person", "password1": GOOD_PASSWORD})
        self.client.logout()
        self.assertContains(self.client.get(url), "already been used")