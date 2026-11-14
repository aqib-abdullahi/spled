from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from security.models import Attempt
from twofactor import services
from twofactor.models import BackupCode, TwoFactor
from twofactor.totp import hotp, step_at

GOOD = "s3cure-Passw0rd!"
FROZEN = 1_700_000_000.0


def wrong_code(secret):
    valid = {hotp(secret, step_at(FROZEN) + k) for k in (-1, 0, 1)}
    return next(c for c in ("000000", "111111", "222222") if c not in valid)


class Base(TestCase):
    def setUp(self):
        patcher = mock.patch("twofactor.totp.now", return_value=FROZEN)
        patcher.start()
        self.addCleanup(patcher.stop)

    def code(self, secret, offset=0):
        return hotp(secret, step_at(FROZEN) + offset)

    def enable(self, user):
        tf = services.begin_setup(user)
        codes = services.confirm_setup(user, self.code(tf.secret))
        TwoFactor.objects.filter(user=user).update(last_used_step=step_at(FROZEN) - 10)
        return tf.secret, codes


class SignInFlowTests(Base):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("a@example.com", GOOD, full_name="Ada")
        self.secret, self.codes = self.enable(self.user)

    def sign_in(self, email="a@example.com", password=GOOD, **extra):
        data = {"username": email, "password": password}
        data.update(extra)
        return self.client.post(reverse("signin"), data)

    def verify(self, code):
        return self.client.post(reverse("signin_verify"), {"code": code})

    def signed_in(self):
        return self.client.get(reverse("overview")).status_code == 200

    def test_user_without_two_factor_signs_in_directly(self):
        User.objects.create_user("c@example.com", GOOD, full_name="C")
        r = self.sign_in("c@example.com")
        self.assertRedirects(r, reverse("overview"))

    def test_password_alone_does_not_sign_in_a_two_factor_user(self):
        r = self.sign_in()
        self.assertRedirects(r, reverse("signin_verify"))
        self.assertFalse(self.signed_in())

    def test_correct_code_signs_in(self):
        self.sign_in()
        r = self.verify(self.code(self.secret))
        self.assertRedirects(r, reverse("overview"))
        self.assertTrue(self.signed_in())

    def test_the_original_destination_is_kept(self):
        self.sign_in(next="/app/sites/")
        r = self.verify(self.code(self.secret))
        self.assertRedirects(r, "/app/sites/", fetch_redirect_response=False)

    def test_wrong_code_is_refused(self):
        self.sign_in()
        r = self.verify(wrong_code(self.secret))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "isn’t right")
        self.assertFalse(self.signed_in())

    def test_badly_formatted_code_gets_a_hint_and_is_not_counted(self):
        self.sign_in()
        r = self.verify("abc")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Enter the 6-digit code from your authenticator app")
        self.assertEqual(Attempt.objects.count(), 0)

    def test_a_plausible_but_wrong_code_is_counted(self):
        self.sign_in()
        r = self.verify(wrong_code(self.secret))
        self.assertContains(r, "isn’t right")
        self.assertEqual(Attempt.objects.count(), 2)

    def test_malformed_codes_never_lock_the_account(self):
        self.sign_in()
        for _ in range(8):
            self.assertEqual(self.verify("abc").status_code, 200)
        r = self.verify(self.code(self.secret))
        self.assertRedirects(r, reverse("overview"))

    def test_code_cannot_be_replayed_at_the_next_sign_in(self):
        code = self.code(self.secret)
        self.sign_in()
        self.assertRedirects(self.verify(code), reverse("overview"))
        self.client.post(reverse("signout"))
        self.sign_in()
        r = self.verify(code)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "isn’t right")
        self.assertFalse(self.signed_in())

    def test_backup_code_signs_in_once_and_sends_an_email(self):
        self.sign_in()
        self.assertRedirects(self.verify(self.codes[0]), reverse("overview"))
        self.assertEqual(mail.outbox[-1].subject, "A backup code was used to sign in")
        self.assertEqual(mail.outbox[-1].to, ["a@example.com"])
        self.client.post(reverse("signout"))
        self.sign_in()
        self.assertEqual(self.verify(self.codes[0]).status_code, 200)
        self.assertRedirects(self.verify(self.codes[1].upper()), reverse("overview"))

    def test_verify_page_needs_a_started_sign_in(self):
        r = self.client.get(reverse("signin_verify"))
        self.assertRedirects(r, reverse("signin"))

    def test_a_stale_sign_in_is_refused(self):
        self.sign_in()
        session = self.client.session
        pending = session["pending_2fa"]
        pending["at"] -= 3600
        session["pending_2fa"] = pending
        session.save()
        r = self.client.get(reverse("signin_verify"))
        self.assertRedirects(r, reverse("signin"))

    def test_a_deactivated_user_cannot_finish(self):
        self.sign_in()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        r = self.verify(self.code(self.secret))
        self.assertRedirects(r, reverse("signin"))
        self.assertFalse(self.signed_in())

    def test_five_wrong_codes_lock_the_user_even_for_the_right_code(self):
        self.sign_in()
        for _ in range(5):
            self.assertEqual(self.verify(wrong_code(self.secret)).status_code, 200)
        r = self.verify(self.code(self.secret))
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r["Retry-After"], "900")
        self.assertFalse(self.signed_in())

    def test_other_users_are_not_locked(self):
        other_user = User.objects.create_user("b@example.com", GOOD, full_name="B")
        other_secret, _ = self.enable(other_user)
        self.sign_in()
        for _ in range(5):
            self.verify(wrong_code(self.secret))
        other = self.client_class()
        other.post(reverse("signin"), {"username": "b@example.com", "password": GOOD})
        r = other.post(reverse("signin_verify"), {"code": self.code(other_secret)})
        self.assertRedirects(r, reverse("overview"))

    def test_an_external_next_is_ignored(self):
        self.sign_in(next="https://evil.example/steal")
        r = self.verify(self.code(self.secret))
        self.assertRedirects(r, reverse("overview"))

    def test_a_wrong_password_never_reaches_the_code_step(self):
        r = self.sign_in(password="nope")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "don’t match")
        self.assertNotIn("pending_2fa", self.client.session)


class SecurityPageTests(Base):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("a@example.com", GOOD, full_name="Ada")
        self.client.login(username="a@example.com", password=GOOD)

    def test_page_needs_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("account_security")).status_code, 302)

    def test_page_offers_setup_when_off(self):
        r = self.client.get(reverse("account_security"))
        self.assertContains(r, reverse("twofactor_setup"))

    def test_setup_page_shows_the_secret_and_a_link(self):
        r = self.client.get(reverse("twofactor_setup"))
        tf = TwoFactor.objects.get(user=self.user)
        self.assertFalse(tf.is_active)
        self.assertContains(r, services.format_secret(tf.secret))
        self.assertContains(r, "otpauth://totp/")

    def test_setup_page_keeps_the_same_secret(self):
        self.client.get(reverse("twofactor_setup"))
        first = TwoFactor.objects.get(user=self.user).secret
        self.client.get(reverse("twofactor_setup"))
        self.assertEqual(TwoFactor.objects.count(), 1)
        self.assertEqual(TwoFactor.objects.get(user=self.user).secret, first)

    def test_a_wrong_setup_code_is_refused(self):
        tf = services.begin_setup(self.user)
        r = self.client.post(reverse("twofactor_setup"), {"code": wrong_code(tf.secret)})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "isn’t right")
        self.assertFalse(services.has_two_factor(self.user))

    def test_the_right_setup_code_turns_it_on_and_shows_codes_once(self):
        tf = services.begin_setup(self.user)
        r = self.client.post(reverse("twofactor_setup"), {"code": self.code(tf.secret)})
        self.assertEqual(r.status_code, 200)
        codes = r.context["codes"]
        self.assertEqual(len(codes), 10)
        self.assertContains(r, codes[0])
        self.assertIn("no-store", r["Cache-Control"])
        self.assertTrue(services.has_two_factor(self.user))
        again = self.client.get(reverse("account_security"))
        self.assertNotContains(again, codes[0])

    def test_setup_sends_an_email(self):
        tf = services.begin_setup(self.user)
        self.client.post(reverse("twofactor_setup"), {"code": self.code(tf.secret)})
        self.assertEqual(mail.outbox[-1].subject, "Two-step verification turned on")
        self.assertEqual(mail.outbox[-1].to, ["a@example.com"])

    def test_setup_redirects_when_already_on(self):
        self.enable(self.user)
        r = self.client.get(reverse("twofactor_setup"))
        self.assertRedirects(r, reverse("account_security"))

    def test_page_shows_the_remaining_codes_when_on(self):
        _, codes = self.enable(self.user)
        self.assertContains(self.client.get(reverse("account_security")), "10 backup codes left")
        services.verify_code(self.user, codes[0])
        self.assertContains(self.client.get(reverse("account_security")), "9 backup codes left")

    def test_disable_needs_password_and_code(self):
        secret, _ = self.enable(self.user)
        url = reverse("twofactor_disable")
        attempts = (
            {"password": "nope", "code": self.code(secret)},
            {"password": GOOD, "code": wrong_code(secret)},
            {"password": GOOD},
            {},
        )
        for data in attempts:
            r = self.client.post(url, data)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(services.has_two_factor(self.user))

    def test_disable_with_everything_correct(self):
        secret, _ = self.enable(self.user)
        r = self.client.post(
            reverse("twofactor_disable"), {"password": GOOD, "code": self.code(secret)}
        )
        self.assertRedirects(r, reverse("account_security"))
        self.assertFalse(services.has_two_factor(self.user))
        self.assertEqual(BackupCode.objects.count(), 0)
        self.assertEqual(mail.outbox[-1].subject, "Two-step verification turned off")

    def test_disable_only_accepts_post(self):
        self.enable(self.user)
        self.assertEqual(self.client.get(reverse("twofactor_disable")).status_code, 405)

    def test_wrong_attempts_are_counted_and_lock(self):
        secret, _ = self.enable(self.user)
        url = reverse("twofactor_disable")
        for _ in range(5):
            r = self.client.post(url, {"password": GOOD, "code": wrong_code(secret)})
            self.assertEqual(r.status_code, 200)
        r = self.client.post(url, {"password": GOOD, "code": self.code(secret)})
        self.assertContains(r, "Too many attempts")
        self.assertTrue(services.has_two_factor(self.user))

    def test_new_codes_replace_the_old_ones(self):
        secret, old = self.enable(self.user)
        r = self.client.post(
            reverse("twofactor_codes"), {"password": GOOD, "code": self.code(secret)}
        )
        self.assertEqual(r.status_code, 200)
        new = r.context["codes"]
        self.assertEqual(len(new), 10)
        self.assertTrue(set(new).isdisjoint(old))
        self.assertEqual(mail.outbox[-1].subject, "New backup codes generated")
        self.assertIsNone(services.verify_code(self.user, old[0]))
        self.assertEqual(services.verify_code(self.user, new[0]), "backup")

    def test_new_codes_need_password_and_code(self):
        secret, old = self.enable(self.user)
        r = self.client.post(
            reverse("twofactor_codes"), {"password": "nope", "code": self.code(secret)}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(services.verify_code(self.user, old[0]), "backup")

    def test_sign_in_stops_asking_after_disabling(self):
        self.enable(self.user)
        services.disable(self.user)
        self.client.logout()
        r = self.client.post(reverse("signin"), {"username": "a@example.com", "password": GOOD})
        self.assertRedirects(r, reverse("overview"))

    def test_menu_has_a_security_link(self):
        r = self.client.get(reverse("overview"))
        self.assertContains(r, reverse("account_security"))


class AdminGateTests(Base):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_superuser("boss@example.com", GOOD, full_name="Boss")
        self.user = User.objects.create_user("a@example.com", GOOD, full_name="Ada")

    def test_anonymous_is_sent_to_our_sign_in(self):
        r = self.client.get("/admin/login/")
        self.assertRedirects(r, "/signin/?next=%2Fadmin%2F", fetch_redirect_response=False)

    def test_posting_credentials_to_the_admin_login_does_not_sign_in(self):
        r = self.client.post("/admin/login/", {"username": "boss@example.com", "password": GOOD})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_non_staff_gets_a_403(self):
        self.client.login(username="a@example.com", password=GOOD)
        self.assertEqual(self.client.get("/admin/login/").status_code, 403)

    def test_staff_with_two_factor_reaches_the_admin_after_the_code(self):
        secret, _ = self.enable(self.staff)
        r = self.client.get("/admin/")
        self.assertRedirects(r, "/admin/login/?next=/admin/", fetch_redirect_response=False)
        self.client.post(
            reverse("signin"),
            {"username": "boss@example.com", "password": GOOD, "next": "/admin/"},
        )
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        r = self.client.post(reverse("signin_verify"), {"code": self.code(secret)})
        self.assertRedirects(r, "/admin/")
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_next_is_kept_and_checked(self):
        r = self.client.get("/admin/login/", {"next": "/admin/auth/"})
        self.assertRedirects(r, "/signin/?next=%2Fadmin%2Fauth%2F", fetch_redirect_response=False)
        r = self.client.get("/admin/login/", {"next": "https://evil.example/"})
        self.assertRedirects(r, "/signin/?next=%2Fadmin%2F", fetch_redirect_response=False)

    def test_signed_in_staff_are_sent_straight_to_the_admin(self):
        self.client.login(username="boss@example.com", password=GOOD)
        r = self.client.get("/admin/login/")
        self.assertRedirects(r, "/admin/", fetch_redirect_response=False)