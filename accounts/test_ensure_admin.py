import io
import os
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

User = get_user_model()
PASSWORD = "Zq8!mT4#vLpW"
ROOT = Path(settings.BASE_DIR)


def run_ensure(**env):
    """Run ensure_admin with only the ADMIN_* variables given, whatever the shell has."""
    base = {k: v for k, v in os.environ.items() if not k.startswith("ADMIN_")}
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, {**base, **env}, clear=True):
        call_command("ensure_admin", stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


class EnsureAdminTests(TestCase):
    def test_nothing_set_does_nothing(self):
        out = run_ensure()
        self.assertEqual(User.objects.count(), 0)
        self.assertIn("not set", out)

    def test_creates_a_superuser_from_a_password_hash(self):
        run_ensure(ADMIN_EMAIL="Boss@Example.com", ADMIN_NAME="The Boss",
                   ADMIN_PASSWORD_HASH=make_password(PASSWORD))
        user = User.objects.get()
        self.assertEqual(user.email, "boss@example.com")
        self.assertEqual(user.full_name, "The Boss")
        self.assertTrue(user.is_staff and user.is_superuser and user.is_active)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertIsNotNone(user.email_verified_at)

    def test_creates_from_a_plain_password_when_there_is_no_hash(self):
        run_ensure(ADMIN_EMAIL="boss@example.com", ADMIN_PASSWORD=PASSWORD)
        user = User.objects.get()
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))

    def test_the_hash_wins_over_a_plain_password(self):
        run_ensure(ADMIN_EMAIL="boss@example.com", ADMIN_PASSWORD="Different!Pass99",
                   ADMIN_PASSWORD_HASH=make_password(PASSWORD))
        self.assertTrue(User.objects.get().check_password(PASSWORD))

    def test_an_existing_account_is_never_changed(self):
        existing = User.objects.create_user("boss@example.com", "OldPassw0rd!x", full_name="Old")
        out = run_ensure(ADMIN_EMAIL="boss@example.com", ADMIN_PASSWORD_HASH=make_password(PASSWORD))
        existing.refresh_from_db()
        self.assertTrue(existing.check_password("OldPassw0rd!x"))
        self.assertFalse(existing.is_staff or existing.is_superuser)
        self.assertEqual(User.objects.count(), 1)
        self.assertIn("already exists", out)

    def test_capital_letters_in_the_email_do_not_create_a_second_account(self):
        User.objects.create_user("boss@example.com", "OldPassw0rd!x", full_name="Old")
        run_ensure(ADMIN_EMAIL="BOSS@EXAMPLE.COM", ADMIN_PASSWORD_HASH=make_password(PASSWORD))
        self.assertEqual(User.objects.count(), 1)

    def test_a_weak_password_is_refused_and_nothing_is_created(self):
        with self.assertRaises(CommandError) as ctx:
            run_ensure(ADMIN_EMAIL="boss@example.com", ADMIN_PASSWORD="short")
        self.assertIn("too weak", str(ctx.exception))
        self.assertEqual(User.objects.count(), 0)

    def test_an_invalid_hash_is_refused_and_nothing_is_created(self):
        with self.assertRaises(CommandError) as ctx:
            run_ensure(ADMIN_EMAIL="boss@example.com", ADMIN_PASSWORD_HASH="not-a-hash")
        self.assertIn("hash_password", str(ctx.exception))
        self.assertEqual(User.objects.count(), 0)

    def test_a_missing_password_is_refused(self):
        with self.assertRaises(CommandError) as ctx:
            run_ensure(ADMIN_EMAIL="boss@example.com")
        self.assertIn("ADMIN_PASSWORD_HASH", str(ctx.exception))
        self.assertEqual(User.objects.count(), 0)

    def test_a_bad_email_is_refused(self):
        with self.assertRaises(CommandError):
            run_ensure(ADMIN_EMAIL="not-an-email", ADMIN_PASSWORD=PASSWORD)
        self.assertEqual(User.objects.count(), 0)

    def test_a_missing_name_defaults_to_administrator(self):
        run_ensure(ADMIN_EMAIL="boss@example.com", ADMIN_PASSWORD=PASSWORD)
        self.assertEqual(User.objects.get().full_name, "Administrator")

    def test_the_password_and_hash_are_never_printed(self):
        hashed = make_password(PASSWORD)
        out = run_ensure(ADMIN_EMAIL="one@example.com", ADMIN_PASSWORD_HASH=hashed)
        out += run_ensure(ADMIN_EMAIL="two@example.com", ADMIN_PASSWORD=PASSWORD)
        self.assertNotIn(PASSWORD, out)
        self.assertNotIn(hashed, out)
        self.assertEqual(User.objects.count(), 2)

    def test_running_twice_is_safe(self):
        env = dict(ADMIN_EMAIL="boss@example.com", ADMIN_PASSWORD_HASH=make_password(PASSWORD))
        run_ensure(**env)
        out = run_ensure(**env)
        self.assertEqual(User.objects.count(), 1)
        self.assertIn("already exists", out)

    def test_stray_whitespace_in_the_settings_is_cleaned(self):
        run_ensure(ADMIN_EMAIL=" boss@example.com\n", ADMIN_NAME=" The Boss \n",
                   ADMIN_PASSWORD_HASH=make_password(PASSWORD) + "\n")
        user = User.objects.get()
        self.assertEqual((user.email, user.full_name), ("boss@example.com", "The Boss"))
        self.assertTrue(user.check_password(PASSWORD))


class HashPasswordTests(SimpleTestCase):
    def run_command(self, *answers):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("accounts.management.commands.hash_password.getpass", side_effect=list(answers)):
            call_command("hash_password", stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_prints_a_hash_that_matches_the_password(self):
        out, _err = self.run_command(PASSWORD, PASSWORD)
        self.assertTrue(check_password(PASSWORD, out.strip()))

    def test_two_different_answers_are_refused(self):
        with self.assertRaises(CommandError) as ctx:
            self.run_command(PASSWORD, PASSWORD + "x")
        self.assertIn("differ", str(ctx.exception))

    def test_a_weak_password_is_refused(self):
        with self.assertRaises(CommandError) as ctx:
            self.run_command("short", "short")
        self.assertIn("weak", str(ctx.exception))

    def test_only_the_hash_goes_to_standard_output(self):
        out, err = self.run_command(PASSWORD, PASSWORD)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertNotIn(PASSWORD, out + err)
        self.assertIn("ADMIN_PASSWORD_HASH", err)


class WiringTests(SimpleTestCase):
    def test_entrypoint_creates_the_admin_after_migrating_and_survives_a_failure(self):
        text = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
        self.assertLess(text.index("manage.py migrate"), text.index("manage.py ensure_admin"))
        self.assertLess(text.index("manage.py ensure_admin"), text.index("exec gunicorn"))
        line = [x for x in text.splitlines() if "manage.py ensure_admin" in x][0]
        self.assertIn("||", line)

    def test_the_blueprint_asks_for_the_admin_settings_and_never_a_plain_password(self):
        text = (ROOT / "render.yaml").read_text(encoding="utf-8").replace("\r\n", "\n")
        for key in ("ADMIN_EMAIL", "ADMIN_NAME", "ADMIN_PASSWORD_HASH"):
            with self.subTest(key=key):
                self.assertRegex(text, r"- key: %s\n\s+sync: false" % key)
        self.assertIsNone(re.search(r"- key: ADMIN_PASSWORD\s*$", text, re.M))