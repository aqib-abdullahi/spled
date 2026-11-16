from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import OperationalError
from django.test import TestCase
from django.urls import reverse

ROOT = Path(settings.BASE_DIR)


class HealthCheckTests(TestCase):
    def test_ok_is_tiny_and_needs_no_sign_in(self):
        r = self.client.get(reverse("healthz"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"ok")
        self.assertTrue(r["Content-Type"].startswith("text/plain"))

    def test_works_without_the_trailing_slash(self):
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_never_cached(self):
        self.assertEqual(self.client.get(reverse("healthz"))["Cache-Control"], "no-store")

    def test_allows_head_and_rejects_post(self):
        self.assertEqual(self.client.head(reverse("healthz")).status_code, 200)
        self.assertEqual(self.client.post(reverse("healthz")).status_code, 405)

    def test_database_down_gives_503_without_leaking_details(self):
        with mock.patch("web.health.connection") as conn:
            conn.cursor.side_effect = OperationalError("secret host details")
            with self.assertLogs("web.health", level="ERROR"):
                r = self.client.get(reverse("healthz"))
        self.assertEqual(r.status_code, 503)
        self.assertNotContains(r, "secret host details", status_code=503)
        self.assertEqual(r["Cache-Control"], "no-store")


class ProductionWiringTests(TestCase):
    def test_static_root_is_separate_from_the_source_folder(self):
        self.assertEqual(Path(settings.STATIC_ROOT).name, "staticfiles")
        self.assertNotIn(settings.STATIC_ROOT, settings.STATICFILES_DIRS)

    def test_production_requirements_extend_the_normal_ones(self):
        lines = (ROOT / "requirements-prod.txt").read_text(encoding="utf-8").split()
        self.assertIn("-r", lines)
        self.assertIn("requirements.txt", lines)
        self.assertIn("whitenoise", lines)
        self.assertIn("gunicorn", lines)

    def test_settings_wire_up_whitenoise_only_when_debug_is_off(self):
        text = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
        block = text[text.index("Step 48"):]
        self.assertIn("if not DEBUG:", block)
        self.assertIn("whitenoise.middleware.WhiteNoiseMiddleware", block)
        self.assertIn("CompressedStaticFilesStorage", block)

    def test_collectstatic_output_is_not_committed(self):
        self.assertIn("staticfiles/", (ROOT / ".gitignore").read_text(encoding="utf-8"))