from django.test import SimpleTestCase

from .services import looks_like_a_code


class LooksLikeACodeTests(SimpleTestCase):
    def test_six_digits_are_plausible(self):
        for text in ("123456", "123 456", "123-456", "  123456  "):
            self.assertTrue(looks_like_a_code(text), text)

    def test_ten_character_backup_codes_are_plausible(self):
        for text in ("abcde-fghjk", "ABCDE FGHJK", "abcdefghjk"):
            self.assertTrue(looks_like_a_code(text), text)

    def test_anything_else_is_not(self):
        for text in ("", None, "abc", "12345", "1234567", "abcdef", "abcde-fghj", "\u0661\u0662\u0663\u0664\u0665\u0666"):
            self.assertFalse(looks_like_a_code(text), repr(text))
