import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

PATH = Path(settings.BASE_DIR) / "requirements.txt"
WINDOWS_ONLY = {"pywin32", "pypiwin32", "pywin32-ctypes", "pywinpty"}
PINNED = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9,._-]+\])?==[A-Za-z0-9.!+_-]+$")


def requirement_lines():
    text = PATH.read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


class RequirementsFileTests(SimpleTestCase):
    def test_file_is_plain_utf8_without_a_byte_order_mark(self):
        raw = PATH.read_bytes()
        self.assertNotIn(b"\x00", raw)  # UTF-16, as PowerShell's > writes it, has null bytes
        self.assertFalse(raw.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")))
        raw.decode("utf-8")

    def test_every_line_is_a_pinned_requirement(self):
        lines = requirement_lines()
        self.assertGreater(len(lines), 5)
        for line in lines:
            with self.subTest(line=line):
                self.assertRegex(line, PINNED)

    def test_no_windows_only_packages(self):
        names = {PINNED.match(line).group(1).lower() for line in requirement_lines() if PINNED.match(line)}
        self.assertEqual(names & WINDOWS_ONLY, set())