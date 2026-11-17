import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)


def lines_of(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return text, [line.rstrip() for line in text.splitlines()]


class BlueprintShapeTests(SimpleTestCase):
    def setUp(self):
        self.text, self.lines = lines_of("render.yaml")

    def test_service_fields_sit_under_the_list_item(self):
        self.assertIn("services:", self.lines)
        self.assertIn("  - type: web", self.lines)
        for field in ("name: spled-rehearsal", "runtime: docker", "plan: free",
                      "healthCheckPath: /livez/", "envVars:"):
            with self.subTest(field=field):
                self.assertIn("    " + field, self.lines)

    def test_env_vars_are_a_properly_indented_list(self):
        keys = [line for line in self.lines if "- key:" in line]
        self.assertGreaterEqual(len(keys), 10)
        for line in keys:
            with self.subTest(line=line):
                self.assertRegex(line, r"^      - key: [A-Z][A-Z0-9_]*$")
        for line in self.lines:
            stripped = line.strip()
            if stripped.startswith(("value:", "sync:", "generateValue:")):
                with self.subTest(line=line):
                    self.assertTrue(line.startswith("        ") and not line.startswith("         "))

    def test_no_misspelled_blueprint_fields(self):
        for wrong in ("generatedValue", "-type:", "-key:", "sync:false", "sync: False"):
            with self.subTest(wrong=wrong):
                self.assertNotIn(wrong, self.text)

    def test_yaml_and_docker_files_keep_linux_line_endings_in_git(self):
        text, _lines = lines_of(".gitattributes")
        for rule in ("*.yaml text eol=lf", "Dockerfile text eol=lf", "*.sh text eol=lf"):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)