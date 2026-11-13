import hashlib
import os
import secrets
import subprocess
import sys
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import Attempt
from .throttle import DEFAULT_RULES, _hash, clear, client_ip, count, hit, limited

GOOD = "s3cure-Passw0rd!"


def signup_data(email, **extra):
    data = {
        "full_name": "Ada Obi", "email": email, "organisation_name": "Works Dept",
        "kind": "government", "password1": GOOD,
    }
    data.update(extra)
    return data


class ThrottleTests(TestCase):
    def test_the_limit_blocks_at_exactly_the_configured_count(self):
        limit, _ = DEFAULT_RULES["signin_pair"]
        for _i in range(limit - 1):
            hit("signin_pair", "k")
        self.assertFalse(limited("signin_pair", "k"))
        hit("signin_pair", "k")
        self.assertTrue(limited("signin_pair", "k"))

    def test_attempts_outside_the_window_do_not_count(self):
        _, window = DEFAULT_RULES["signin_pair"]
        Attempt.objects.create(
            scope="signin_pair", key_hash=_hash("k"),
            created_at=timezone.now() - timedelta(seconds=window + 60),
        )
        self.assertEqual(count("signin_pair", "k"), 0)

    def test_keys_are_hashed_and_case_insensitive(self):
        hit("email_target", "Victim@Example.com")
        self.assertEqual(count("email_target", "victim@example.com"), 1)
        stored = Attempt.objects.get()
        self.assertEqual(len(stored.key_hash), 64)
        self.assertNotIn("victim", stored.key_hash)

    def test_scopes_and_keys_are_independent(self):
        hit("signin_pair", "x")
        self.assertEqual(count("signin_ip", "x"), 0)
        self.assertEqual(count("signin_pair", "y"), 0)

    def test_clear_removes_only_the_matching_attempts(self):
        hit("signin_pair", "a")
        hit("signin_pair", "a")
        hit("signin_pair", "b")
        clear("signin_pair", "a")
        self.assertEqual(count("signin_pair", "a"), 0)
        self.assertEqual(count("signin_pair", "b"), 1)

    def test_an_unknown_scope_is_an_error(self):
        with self.assertRaises(KeyError):
            limited("nope", "x")
        with self.assertRaises(KeyError):
            hit("nope", "x")

    def test_limits_can_be_overridden_in_settings(self):
        with override_settings(SPLED_LIMITS={"signin_pair": (1, 60)}):
            hit("signin_pair", "k")
            self.assertTrue(limited("signin_pair", "k"))


class ClientIpTests(TestCase):
    def request(self, forwarded=None):
        extra = {"REMOTE_ADDR": "10.0.0.5"}
        if forwarded:
            extra["HTTP_X_FORWARDED_FOR"] = forwarded
        return RequestFactory().get("/", **extra)

    def test_the_connection_address_is_used_by_default(self):
        self.assertEqual(client_ip(self.request("6.6.6.6")), "10.0.0.5")

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_one_trusted_proxy_uses_the_rightmost_entry(self):
        self.assertEqual(client_ip(self.request("6.6.6.6, 203.0.113.9")), "203.0.113.9")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_two_trusted_proxies_use_the_second_from_the_right(self):
        self.assertEqual(client_ip(self.request("1.1.1.1, 2.2.2.2, 3.3.3.3")), "2.2.2.2")

    @override_settings(TRUSTED_PROXY_COUNT=2)
    def test_too_few_entries_fall_back_to_the_connection_address(self):
        self.assertEqual(client_ip(self.request("9.9.9.9")), "10.0.0.5")

    def test_no_address_at_all_gives_unknown(self):
        request = RequestFactory().get("/")
        request.META.pop("REMOTE_ADDR", None)
        self.assertEqual(client_ip(request), "unknown")


class SignInThrottleTests(TestCase):
    def setUp(self):
        self.url = reverse("signin")
        User.objects.create_user("a@example.com", GOOD, full_name="A")
        User.objects.create_user("b@example.com", GOOD, full_name="B")

    def post(self, email, password, client=None):
        return (client or self.client).post(
            self.url, {"username": email, "password": password}
        )

    def fail_times(self, email, n):
        for _ in range(n):
            self.assertEqual(self.post(email, "wrong").status_code, 200)

    def test_the_sixth_failed_attempt_is_blocked_even_with_the_right_password(self):
        self.fail_times("a@example.com", 5)
        self.assertEqual(self.post("a@example.com", GOOD).status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_other_accounts_from_the_same_address_are_not_affected(self):
        self.fail_times("a@example.com", 5)
        self.assertEqual(self.post("b@example.com", GOOD).status_code, 302)

    def test_a_successful_sign_in_resets_the_count(self):
        self.fail_times("a@example.com", 4)
        self.assertEqual(self.post("a@example.com", GOOD).status_code, 302)
        self.client.logout()
        self.fail_times("a@example.com", 5)

    def test_the_address_wide_limit_applies_across_accounts(self):
        with override_settings(SPLED_LIMITS={"signin_ip": (3, 900)}):
            for i in range(3):
                self.assertEqual(self.post(f"nobody{i}@example.com", "wrong").status_code, 200)
            self.assertEqual(self.post("nobody9@example.com", "wrong").status_code, 429)

    def test_the_blocked_page_explains_and_sets_retry_after(self):
        self.fail_times("a@example.com", 5)
        r = self.post("a@example.com", "wrong")
        self.assertContains(r, "Too many attempts", status_code=429)
        self.assertEqual(r["Retry-After"], "900")

    def test_get_requests_are_never_blocked(self):
        self.fail_times("a@example.com", 5)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_requests_that_fail_the_csrf_check_are_not_counted(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        for _ in range(8):
            self.assertEqual(self.post("a@example.com", GOOD, client=csrf_client).status_code, 403)
        self.assertEqual(Attempt.objects.count(), 0)
        self.assertEqual(self.post("a@example.com", GOOD).status_code, 302)

    def test_unknown_and_known_accounts_are_throttled_the_same_way(self):
        self.fail_times("nobody@example.com", 5)
        self.assertEqual(self.post("nobody@example.com", "wrong").status_code, 429)


class SignUpThrottleTests(TestCase):
    def setUp(self):
        self.url = reverse("signup")

    @override_settings(SPLED_LIMITS={"signup_ip": (2, 3600)})
    def test_the_address_limit_blocks_extra_sign_ups(self):
        for n in range(2):
            r = self.client.post(self.url, signup_data(f"u{n}@example.com"))
            self.assertRedirects(r, reverse("signup_sent"))
        r = self.client.post(self.url, signup_data("u3@example.com"))
        self.assertEqual(r.status_code, 429)
        self.assertFalse(User.objects.filter(email="u3@example.com").exists())

    @override_settings(SPLED_LIMITS={"signup_ip": (2, 3600)})
    def test_failed_attempts_do_not_use_up_the_allowance(self):
        for n in range(3):
            r = self.client.post(self.url, signup_data(f"bad{n}@example.com", password1="abc"))
            self.assertEqual(r.status_code, 200)
        for n in range(2):
            r = self.client.post(self.url, signup_data(f"ok{n}@example.com"))
            self.assertRedirects(r, reverse("signup_sent"))

    @override_settings(SPLED_LIMITS={"email_target": (2, 3600)})
    def test_emails_to_one_address_are_capped_without_telling_anyone(self):
        for _ in range(3):
            r = self.client.post(self.url, signup_data("same@example.com"))
            self.assertRedirects(r, reverse("signup_sent"))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(User.objects.filter(email="same@example.com").count(), 1)


class EmailFlowThrottleTests(TestCase):
    def reset(self, email):
        return self.client.post(reverse("password_reset"), {"email": email})

    @override_settings(SPLED_LIMITS={"email_target": (2, 3600)})
    def test_reset_emails_are_capped_per_address(self):
        User.objects.create_user("p@example.com", GOOD, full_name="P")
        for _ in range(3):
            self.assertRedirects(self.reset("p@example.com"), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 2)

    def test_reset_looks_the_same_for_an_unknown_address(self):
        self.assertRedirects(self.reset("nobody@example.com"), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(SPLED_LIMITS={"email_ip": (2, 3600)})
    def test_reset_emails_are_capped_per_requesting_address(self):
        for n in range(3):
            User.objects.create_user(f"u{n}@example.com", GOOD, full_name="U")
        for n in range(3):
            self.assertRedirects(self.reset(f"u{n}@example.com"), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(SPLED_LIMITS={"email_target": (1, 3600)})
    def test_resending_verification_is_capped(self):
        User.objects.create_user("u@example.com", GOOD, full_name="U", is_active=False)
        for _ in range(2):
            r = self.client.post(reverse("resend_verification"), {"email": "u@example.com"})
            self.assertRedirects(r, reverse("signup_sent"))
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(SPLED_LIMITS={"email_ip": (1, 3600)})
    def test_invalid_requests_do_not_use_up_the_allowance(self):
        User.objects.create_user("p@example.com", GOOD, full_name="P")
        for _ in range(3):
            self.assertEqual(self.reset("nope").status_code, 200)
        self.assertRedirects(self.reset("p@example.com"), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)


class SecurityHeaderTests(TestCase):
    def test_pages_carry_the_extra_security_headers(self):
        r = self.client.get(reverse("signin"))
        self.assertIn("camera=()", r["Permissions-Policy"])
        self.assertIn("geolocation=(self)", r["Permissions-Policy"])
        self.assertIn("frame-ancestors 'none'", r["Content-Security-Policy"])
        self.assertIn("object-src 'none'", r["Content-Security-Policy"])
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_error_pages_carry_them_too(self):
        r = self.client.get("/no-such-page/")
        self.assertEqual(r.status_code, 404)
        self.assertIn("frame-ancestors", r["Content-Security-Policy"])


class HousekeepingTests(TestCase):
    def test_prune_removes_only_old_attempts(self):
        Attempt.objects.create(
            scope="signin_ip", key_hash="a" * 64,
            created_at=timezone.now() - timedelta(days=2),
        )
        Attempt.objects.create(scope="signin_ip", key_hash="b" * 64)
        out = StringIO()
        call_command("prune_attempts", stdout=out)
        self.assertEqual(list(Attempt.objects.values_list("key_hash", flat=True)), ["b" * 64])
        self.assertIn("Removed 1", out.getvalue())

    def test_passwords_need_at_least_ten_characters(self):
        with self.assertRaises(ValidationError):
            validate_password("k7Qm2xP9v")
        validate_password("k7Qm2xP9vL")


def run_manage(*args, **env):
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=settings.BASE_DIR, env={**os.environ, **env},
        capture_output=True, text=True, timeout=180,
    )


class DeploymentSettingsTests(TestCase):
    def test_a_production_configuration_passes_the_deployment_check(self):
        proc = run_manage(
            "check", "--deploy",
            DEBUG="False", SECRET_KEY=secrets.token_urlsafe(64), ALLOWED_HOSTS="example.com",
        )
        output = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn("no issues", output)

    def test_production_refuses_to_start_without_a_secret_key(self):
        proc = run_manage("check", DEBUG="False", SECRET_KEY="", ALLOWED_HOSTS="example.com")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("SECRET_KEY", proc.stdout + proc.stderr)

    def test_production_without_allowed_hosts_is_flagged(self):
        proc = run_manage(
            "check", "--deploy", DEBUG="False", SECRET_KEY=secrets.token_urlsafe(64), ALLOWED_HOSTS="",
        )
        self.assertIn("W020", proc.stdout + proc.stderr)