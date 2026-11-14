import base64
import re
from unittest import mock

from django.test import SimpleTestCase, TestCase

from accounts.models import User

from . import services
from .models import BackupCode, TwoFactor
from .totp import hotp, match, new_secret, provisioning_uri, step_at, totp

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii")
RFC_VECTORS = {
    59: "287082",
    1111111109: "081804",
    1111111111: "050471",
    1234567890: "005924",
    2000000000: "279037",
    20000000000: "353130",
}
FROZEN = 1_700_000_000.0


def wrong_code(secret):
    valid = {hotp(secret, step_at(FROZEN) + k) for k in (-1, 0, 1)}
    return next(c for c in ("000000", "111111", "222222") if c not in valid)


class TotpTests(SimpleTestCase):
    def test_rfc_6238_vectors(self):
        for moment, expected in RFC_VECTORS.items():
            self.assertEqual(totp(RFC_SECRET, moment), expected, moment)

    def test_eight_digit_vector(self):
        self.assertEqual(totp(RFC_SECRET, 59, digits=8), "94287082")

    def test_new_secret_is_32_base32_characters(self):
        secret = new_secret()
        self.assertEqual(len(secret), 32)
        self.assertRegex(secret, r"^[A-Z2-7]{32}$")
        self.assertEqual(len(base64.b32decode(secret)), 20)

    def test_secrets_are_unique(self):
        self.assertEqual(len({new_secret() for _ in range(50)}), 50)

    def test_window_accepts_neighbouring_steps_only(self):
        current = step_at(FROZEN)
        near = {hotp(RFC_SECRET, current + k) for k in (-1, 0, 1)}
        for offset, accepted in ((-1, True), (0, True), (1, True), (-2, False), (2, False)):
            code = hotp(RFC_SECRET, current + offset)
            if not accepted and code in near:
                continue
            self.assertEqual(match(RFC_SECRET, code, FROZEN) is not None, accepted, offset)

    def test_match_returns_the_step(self):
        self.assertEqual(match(RFC_SECRET, "287082", 59), 1)

    def test_used_steps_are_refused(self):
        current = step_at(FROZEN)
        code = hotp(RFC_SECRET, current)
        self.assertEqual(match(RFC_SECRET, code, FROZEN, after_step=current - 1), current)
        self.assertIsNone(match(RFC_SECRET, code, FROZEN, after_step=current))
        later = hotp(RFC_SECRET, current + 1)
        self.assertEqual(match(RFC_SECRET, later, FROZEN, after_step=current), current + 1)

    def test_spaces_and_dashes_are_ignored(self):
        self.assertEqual(match(RFC_SECRET, "287 082", 59), 1)
        self.assertEqual(match(RFC_SECRET, "287-082", 59), 1)

    def test_tabs_and_newlines_are_ignored(self):
        self.assertEqual(match(RFC_SECRET, "287\t082", 59), 1)
        self.assertEqual(match(RFC_SECRET, "287\n082", 59), 1)

    def test_bad_formats_are_refused(self):
        for bad in ("", "12345", "1234567", "abcdef", "١٢٣٤٥٦", "12 34 5", None):
            self.assertIsNone(match(RFC_SECRET, bad, 59), repr(bad))

    def test_provisioning_uri(self):
        uri = provisioning_uri("ABCD", "ada@example.com")
        self.assertTrue(uri.startswith("otpauth://totp/Spled:ada@example.com?"))
        for part in ("secret=ABCD", "issuer=Spled", "digits=6", "period=30", "algorithm=SHA1"):
            self.assertIn(part, uri)
        self.assertIn("a%20b@example.com", provisioning_uri("S", "a b@example.com"))


class ServiceTests(TestCase):
    def setUp(self):
        patcher = mock.patch("twofactor.totp.now", return_value=FROZEN)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user("a@example.com", "pw12345678", full_name="Ada")

    def code(self, secret, offset=0):
        return hotp(secret, step_at(FROZEN) + offset)

    def enable(self):
        tf = services.begin_setup(self.user)
        codes = services.confirm_setup(self.user, self.code(tf.secret))
        TwoFactor.objects.filter(user=self.user).update(last_used_step=step_at(FROZEN) - 10)
        tf.refresh_from_db()
        return tf, codes

    def test_begin_setup_is_idempotent(self):
        first = services.begin_setup(self.user)
        second = services.begin_setup(self.user)
        self.assertEqual((first.pk, first.secret), (second.pk, second.secret))
        self.assertEqual(TwoFactor.objects.count(), 1)

    def test_setup_is_not_active_until_confirmed(self):
        tf = services.begin_setup(self.user)
        self.assertFalse(tf.is_active)
        self.assertFalse(services.has_two_factor(self.user))

    def test_wrong_code_does_not_confirm(self):
        tf = services.begin_setup(self.user)
        self.assertIsNone(services.confirm_setup(self.user, wrong_code(tf.secret)))
        self.assertFalse(services.has_two_factor(self.user))
        self.assertEqual(BackupCode.objects.count(), 0)

    def test_right_code_confirms_and_returns_ten_codes(self):
        tf = services.begin_setup(self.user)
        codes = services.confirm_setup(self.user, self.code(tf.secret))
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        self.assertTrue(services.has_two_factor(self.user))
        tf.refresh_from_db()
        self.assertEqual(tf.last_used_step, step_at(FROZEN))

    def test_backup_codes_are_stored_hashed(self):
        _, codes = self.enable()
        stored = set(BackupCode.objects.values_list("code_hash", flat=True))
        self.assertEqual(len(stored), 10)
        for code in codes:
            self.assertNotIn(code, stored)
            self.assertNotIn(code.replace("-", ""), stored)
        self.assertTrue(all(len(h) == 64 for h in stored))

    def test_backup_codes_look_right(self):
        _, codes = self.enable()
        pattern = r"^[abcdefghjkmnpqrstuvwxyz23456789]{5}-[abcdefghjkmnpqrstuvwxyz23456789]{5}$"
        for code in codes:
            self.assertRegex(code, pattern)

    def test_totp_code_works_once(self):
        tf, _ = self.enable()
        code = self.code(tf.secret)
        self.assertEqual(services.verify_code(self.user, code), "totp")
        self.assertIsNone(services.verify_code(self.user, code))

    def test_neighbouring_step_works_but_older_ones_do_not_after(self):
        tf, _ = self.enable()
        self.assertEqual(services.verify_code(self.user, self.code(tf.secret, 1)), "totp")
        self.assertIsNone(services.verify_code(self.user, self.code(tf.secret, 0)))
        self.assertIsNone(services.verify_code(self.user, self.code(tf.secret, -1)))

    def test_backup_code_works_once(self):
        _, codes = self.enable()
        self.assertEqual(services.verify_code(self.user, codes[0]), "backup")
        self.assertIsNone(services.verify_code(self.user, codes[0]))
        self.assertEqual(services.remaining_backup_codes(self.user), 9)

    def test_backup_code_ignores_case_dashes_and_spaces(self):
        _, codes = self.enable()
        self.assertEqual(services.verify_code(self.user, codes[1].upper()), "backup")
        self.assertEqual(services.verify_code(self.user, codes[2].replace("-", "")), "backup")
        self.assertEqual(services.verify_code(self.user, f"  {codes[3]}  "), "backup")


    def test_wrong_codes_are_refused(self):
        tf, _ = self.enable()
        for bad in (wrong_code(tf.secret), "zzzzz-zzzzz", "", "12345"):
            self.assertIsNone(services.verify_code(self.user, bad), repr(bad))
        self.assertEqual(services.remaining_backup_codes(self.user), 10)

    def test_regenerating_replaces_old_codes(self):
        _, old = self.enable()
        new = services.generate_backup_codes(self.user)
        self.assertEqual(BackupCode.objects.filter(user=self.user).count(), 10)
        self.assertIsNone(services.verify_code(self.user, old[0]))
        self.assertEqual(services.verify_code(self.user, new[0]), "backup")

    def test_disable_removes_everything(self):
        self.enable()
        services.disable(self.user)
        self.assertEqual(TwoFactor.objects.count(), 0)
        self.assertEqual(BackupCode.objects.count(), 0)
        self.assertFalse(services.has_two_factor(self.user))

    def test_other_users_are_unaffected(self):
        self.enable()
        other = User.objects.create_user("b@example.com", "pw12345678", full_name="B")
        self.assertFalse(services.has_two_factor(other))
        self.assertEqual(services.remaining_backup_codes(other), 0)

    def test_remaining_count_drops(self):
        _, codes = self.enable()
        self.assertEqual(services.remaining_backup_codes(self.user), 10)
        services.verify_code(self.user, codes[0])
        self.assertEqual(services.remaining_backup_codes(self.user), 9)

    def test_format_secret_groups_characters(self):
        self.assertEqual(services.format_secret("ABCDEFGH"), "ABCD EFGH")

    def test_qr_is_optional(self):
        result = services.qr_data_uri("otpauth://totp/Spled:a@example.com?secret=ABCD")
        self.assertTrue(result is None or result.startswith("data:image/svg+xml"))
        if result:
            self.assertIsNone(re.search(r"ABCD", result.split(",", 1)[0]))