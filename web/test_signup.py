import re

from django.core import mail, signing
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from organisations.models import Invitation, Membership, Organisation

from .signup_views import VERIFY_SALT

GOOD = "s3cure-Passw0rd!"
OLD = "old-Passw0rd!x"
NEW = "new-S3cure-Passw0rd!"


def signup_data(**extra):
    data = {
        "full_name": "Ada Obi",
        "email": "ada@example.com",
        "organisation_name": "Works Dept",
        "kind": "government",
        "password1": GOOD,
    }
    data.update(extra)
    return data


class SignUpTests(TestCase):
    def sign_up(self, **extra):
        return self.client.post(reverse("signup"), signup_data(**extra))

    def link(self, message=None):
        body = (message or mail.outbox[-1]).body
        return re.search(r"https?://[^\s]+/signup/verify/[^\s]+", body).group(0)

    def token(self):
        return self.link().rstrip("/").rsplit("/", 1)[-1]

    def sign_in(self, password=GOOD):
        return self.client.post(
            reverse("signin"), {"username": "ada@example.com", "password": password}
        )

    def test_page_loads(self):
        self.assertEqual(self.client.get(reverse("signup")).status_code, 200)

    def test_sign_up_creates_user_organisation_membership_and_email(self):
        self.assertRedirects(self.sign_up(), reverse("signup_sent"))
        user = User.objects.get(email="ada@example.com")
        self.assertFalse(user.is_active)
        self.assertIsNone(user.email_verified_at)
        org = Organisation.objects.get()
        self.assertEqual((org.name, org.kind), ("Works Dept", "government"))
        self.assertEqual(org.verification, "pending")
        self.assertEqual(Membership.objects.get(user=user).role, "admin")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ada@example.com"])

    def test_cannot_sign_in_before_verifying(self):
        self.sign_up()
        r = self.sign_in()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Verify your email first")

    def test_wrong_password_for_an_unverified_account_gets_the_generic_message(self):
        self.sign_up()
        r = self.sign_in("wrong")
        self.assertContains(r, "don’t match")
        self.assertNotContains(r, "Verify your email first")

    def test_verification_link_activates_the_account(self):
        self.sign_up()
        r = self.client.get(self.link())
        self.assertContains(r, "Email verified")
        user = User.objects.get(email="ada@example.com")
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.email_verified_at)
        self.assertRedirects(self.sign_in(), reverse("overview"))
        self.assertEqual(Organisation.objects.get().verification, "pending")

    def test_link_cannot_be_used_twice(self):
        self.sign_up()
        self.client.get(self.link())
        first = User.objects.get(email="ada@example.com").email_verified_at
        r = self.client.get(self.link())
        self.assertContains(r, "Already verified")
        self.assertEqual(User.objects.get(email="ada@example.com").email_verified_at, first)

    def test_tampered_link_is_refused(self):
        self.sign_up()
        token = self.token()
        bad = token[:-1] + ("a" if token[-1] != "a" else "b")
        r = self.client.get(reverse("verify_email", args=[bad]))
        self.assertContains(r, "isn’t valid")
        self.assertFalse(User.objects.get(email="ada@example.com").is_active)

    @override_settings(EMAIL_VERIFY_MAX_AGE=-1)
    def test_expired_link_is_refused(self):
        self.sign_up()
        r = self.client.get(self.link())
        self.assertContains(r, "isn’t valid")
        self.assertFalse(User.objects.get(email="ada@example.com").is_active)

    def test_link_for_a_changed_email_is_refused(self):
        self.sign_up()
        user = User.objects.get(email="ada@example.com")
        token = signing.dumps({"u": user.pk, "e": "old@example.com"}, salt=VERIFY_SALT)
        r = self.client.get(reverse("verify_email", args=[token]))
        self.assertContains(r, "isn’t valid")
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_a_deactivated_user_is_not_reactivated_by_a_link(self):
        user = User.objects.create_user(
            "x@example.com", GOOD, full_name="X",
            is_active=False, email_verified_at=timezone.now(),
        )
        token = signing.dumps({"u": user.pk, "e": user.email}, salt=VERIFY_SALT)
        r = self.client.get(reverse("verify_email", args=[token]))
        self.assertContains(r, "Already verified")
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_an_existing_email_reveals_nothing(self):
        User.objects.create_user("ada@example.com", GOOD, full_name="Ada")
        r = self.sign_up()
        self.assertRedirects(r, reverse("signup_sent"))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Organisation.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "You already have a Spled account")
        self.assertNotIn("/signup/verify/", mail.outbox[0].body)

    def test_signing_up_again_while_unverified_resends_the_link(self):
        self.sign_up()
        self.sign_up()
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Organisation.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("/signup/verify/", mail.outbox[1].body)

    def test_a_weak_password_is_refused(self):
        r = self.sign_up(password1="abc")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_a_missing_organisation_name_is_refused(self):
        r = self.sign_up(organisation_name="")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_an_unknown_organisation_type_is_refused(self):
        r = self.sign_up(kind="alien")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Organisation.objects.count(), 0)

    def test_a_signed_in_user_is_sent_to_the_overview(self):
        User.objects.create_user("ada@example.com", GOOD, full_name="Ada")
        self.client.login(username="ada@example.com", password=GOOD)
        self.assertRedirects(self.client.get(reverse("signup")), reverse("overview"))

    def test_resend_only_sends_to_unverified_accounts(self):
        User.objects.create_user("u@example.com", GOOD, full_name="U", is_active=False)
        User.objects.create_user(
            "v@example.com", GOOD, full_name="V", email_verified_at=timezone.now()
        )
        for email in ("u@example.com", "v@example.com", "nobody@example.com"):
            r = self.client.post(reverse("resend_verification"), {"email": email})
            self.assertRedirects(r, reverse("signup_sent"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["u@example.com"])

    def test_email_is_stored_in_lowercase(self):
        self.sign_up(email="ADA@Example.COM")
        self.assertTrue(User.objects.filter(email="ada@example.com").exists())

    def test_people_who_join_by_invitation_are_marked_verified(self):
        org = Organisation.objects.create(name="Org", kind="government")
        admin = User.objects.create_user("boss@example.com", GOOD, full_name="Boss")
        Membership.objects.create(user=admin, organisation=org, role="admin")
        _, raw = Invitation.create_for(org, "new@example.com", "viewer", admin)
        self.client.post(
            reverse("invite_accept", args=[raw]),
            {"full_name": "New Person", "password1": GOOD},
        )
        self.assertIsNotNone(User.objects.get(email="new@example.com").email_verified_at)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("p@example.com", OLD, full_name="P")

    def request_reset(self, email="p@example.com"):
        return self.client.post(reverse("password_reset"), {"email": email})

    def reset_link(self):
        return re.search(r"/reset/[^\s]+", mail.outbox[0].body).group(0)

    def test_page_loads(self):
        self.assertEqual(self.client.get(reverse("password_reset")).status_code, 200)

    def test_reset_email_is_sent_for_a_known_address(self):
        self.assertRedirects(self.request_reset(), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Reset your Spled password")
        self.assertEqual(mail.outbox[0].to, ["p@example.com"])

    def test_an_unknown_address_sends_nothing_but_looks_the_same(self):
        self.assertRedirects(
            self.request_reset("nobody@example.com"), reverse("password_reset_done")
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_full_reset_flow(self):
        self.request_reset()
        r = self.client.get(self.reset_link(), follow=True)
        self.assertEqual(r.status_code, 200)
        set_url = r.redirect_chain[-1][0]
        r = self.client.post(set_url, {"new_password1": NEW, "new_password2": NEW})
        self.assertRedirects(r, reverse("password_reset_complete"))
        self.assertFalse(self.client.login(username="p@example.com", password=OLD))
        self.assertTrue(self.client.login(username="p@example.com", password=NEW))

    def test_a_reset_link_cannot_be_used_twice(self):
        self.request_reset()
        link = self.reset_link()
        r = self.client.get(link, follow=True)
        self.client.post(
            r.redirect_chain[-1][0], {"new_password1": NEW, "new_password2": NEW}
        )
        self.assertContains(self.client.get(link), "isn’t valid")

    def test_mismatched_passwords_are_refused(self):
        self.request_reset()
        r = self.client.get(self.reset_link(), follow=True)
        r = self.client.post(
            r.redirect_chain[-1][0],
            {"new_password1": NEW, "new_password2": NEW + "x"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.client.login(username="p@example.com", password=OLD))

    def test_a_weak_password_is_refused(self):
        self.request_reset()
        r = self.client.get(self.reset_link(), follow=True)
        r = self.client.post(
            r.redirect_chain[-1][0], {"new_password1": "abc", "new_password2": "abc"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.client.login(username="p@example.com", password=OLD))