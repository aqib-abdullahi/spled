import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SKIP = {"static", "staticfiles", "templates", "backups", "private_media", "docker",
        "venv", "env", "node_modules"}


class TestHygieneTests(SimpleTestCase):
    def test_no_test_file_defines_a_method_named_run(self):
        """unittest calls TestCase.run(result) itself. A helper with that name receives the
        result object instead of your arguments and crashes the whole test run."""
        root = Path(settings.BASE_DIR)
        found = []
        for folder in root.iterdir():
            if not folder.is_dir() or folder.name.startswith(".") or folder.name in SKIP:
                continue
            for path in folder.rglob("test*.py"):
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if re.match(r"\s+def run\(self\b", line):
                        found.append(f"{path.relative_to(root)}:{number}")
        self.assertEqual(found, [])