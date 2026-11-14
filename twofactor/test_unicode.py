import base64
from unittest import mock

from django.test import SimpleTestCase, TestCase

from accounts.models import User

from . import services
from .models import BackupCode
from .services import looks_like_a_code, normalise_backup
from .totp import hotp, match, step_at

FROZEN = 1_700_000_000.0
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii")


class NormaliseTests(SimpleTestCase):
    def test_ascii_input_is_lowercased_and_stripped(self):
        self.assertEqual(normalise_backup("ABCDE-fghjk"), "abcdefghjk")
        self.assertEqual(normalise_backup("  abc de  "), "abcde")
        self.assertEqual(normalise_backup("abc.de,"), "abcde")

    def test_any_non_ascii_character_makes_it_invalid(self):
        for text in (
            "abcde-fghj\u0661",  # Arabic-Indic digit one
            "\u212abcde-fghjk",  # Kelvin sign, which lower-cases to a plain k
            "abcde-fghj\u00e9",  # accented letter
            "\uff41bcde-fghjk",  # full-width letter
            "abcde-fghj\u0130",  # dotted capital I
        ):
            self.assertEqual(normalise_backup(text), "", repr(text))

    def test_empty_input_gives_nothing(self):
        self.assertEqual(normalise_backup(""), "")
        self.assertEqual(normalise_backup(None), "")

    def test_plausibility_rejects_non_ascii(self):
        self.assertTrue(looks_like_a_code("abcde-fghjk"))
        self.assertFalse(looks_like_a_code("abcde-fghj\u0661"))
        self.assertFalse(looks_like_a_code("\u0661\u0662\u0663\u0664\u0665\u0666"))


class WhitespaceTests(SimpleTestCase):
    def test_tabs_newlines_and_non_breaking_spaces_are_ignored(self):
        for text in ("287\t082", "287\n082", "287\u00a0082", " 287082\n"):
            self.assertEqual(match(RFC_SECRET, text, 59), 1, repr(text))


class BackupInputTests(TestCase):
    def setUp(self):
        patcher = mock.patch("twofactor.totp.now", return_value=FROZEN)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user("a@example.com", "pw12345678", full_name="Ada")
        tf = services.begin_setup(self.user)
        self.codes = services.confirm_setup(self.user, hotp(tf.secret, step_at(FROZEN)))

    def test_a_real_code_plus_a_non_ascii_character_is_refused(self):
        code = self.codes[0]
        self.assertIsNone(services.verify_code(self.user, code + "\u0661"))
        self.assertEqual(services.remaining_backup_codes(self.user), 10)
        self.assertEqual(services.verify_code(self.user, code), "backup")

    def test_a_lookalike_character_does_not_match(self):
        BackupCode.objects.create(user=self.user, code_hash=services._hash("kkkkk-kkkkk"))
        self.assertIsNone(services.verify_code(self.user, "\u212akkkk-kkkkk"))
        self.assertEqual(services.verify_code(self.user, "kkkkk-kkkkk"), "backup")
