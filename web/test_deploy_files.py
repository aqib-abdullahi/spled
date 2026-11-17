import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from config.db_engine import use_postgis
from config.hosts import render_hosts

ROOT = Path(settings.BASE_DIR)


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def env_blocks(yaml_text):
    """Lines under each '- key: NAME' entry of a Blueprint, up to the next entry."""
    blocks, current = {}, None
    for line in yaml_text.splitlines():
        match = re.match(r"\s*- key:\s*(\S+)", line)
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line.strip())
    return blocks


class LivenessTests(TestCase):
    def test_livez_is_ok_and_touches_no_database(self):
        with self.assertNumQueries(0):
            r = self.client.get(reverse("livez"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"ok")
        self.assertEqual(r["Cache-Control"], "no-store")

    def test_livez_works_without_the_trailing_slash(self):
        self.assertEqual(self.client.get("/livez").status_code, 200)

    def test_livez_allows_head_and_rejects_post(self):
        self.assertEqual(self.client.head(reverse("livez")).status_code, 200)
        self.assertEqual(self.client.post(reverse("livez")).status_code, 405)

    def test_only_the_health_checks_skip_the_https_redirect(self):
        exempt = settings.SECURE_REDIRECT_EXEMPT
        for path in ("livez/", "livez", "healthz/", "healthz"):
            with self.subTest(path=path):
                self.assertTrue(any(re.match(p, path) for p in exempt))
        for path in ("signin/", "app/", "admin/", "projects/", "livez/extra", "x/livez/"):
            with self.subTest(path=path):
                self.assertFalse(any(re.match(p, path) for p in exempt))


class DatabaseEngineTests(SimpleTestCase):
    def test_a_plain_postgres_engine_becomes_postgis(self):
        dbs = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "x"}}
        use_postgis(dbs)
        self.assertEqual(dbs["default"]["ENGINE"], "django.contrib.gis.db.backends.postgis")
        self.assertEqual(dbs["default"]["NAME"], "x")

    def test_postgis_is_left_alone(self):
        dbs = {"default": {"ENGINE": "django.contrib.gis.db.backends.postgis"}}
        use_postgis(dbs)
        self.assertEqual(dbs["default"]["ENGINE"], "django.contrib.gis.db.backends.postgis")

    def test_other_engines_are_left_alone(self):
        dbs = {"default": {"ENGINE": "django.db.backends.sqlite3"}}
        use_postgis(dbs)
        self.assertEqual(dbs["default"]["ENGINE"], "django.db.backends.sqlite3")

    def test_the_live_settings_use_postgis(self):
        engine = settings.DATABASES["default"]["ENGINE"]
        self.assertEqual(engine, "django.contrib.gis.db.backends.postgis")


class RenderHostsTests(SimpleTestCase):
    def test_no_hostname_adds_nothing(self):
        self.assertEqual(render_hosts(""), ([], []))
        self.assertEqual(render_hosts(None), ([], []))

    def test_a_hostname_becomes_an_allowed_host_and_an_https_origin(self):
        self.assertEqual(
            render_hosts(" spled.onrender.com\n"),
            (["spled.onrender.com"], ["https://spled.onrender.com"]),
        )

    def test_anything_that_is_not_a_plain_hostname_is_ignored(self):
        for bad in ("https://spled.onrender.com", "spled.onrender.com/path",
                    "spled.onrender.com:8000", "*", "a b", "-x.com"):
            with self.subTest(bad=bad):
                self.assertEqual(render_hosts(bad), ([], []))


class DockerFilesTests(SimpleTestCase):
    def test_image_is_a_slim_python_with_the_geo_libraries(self):
        text = read("Dockerfile")
        self.assertIn("FROM python:", text)
        self.assertIn("-slim", text)
        self.assertIn("libgdal-dev", text)
        self.assertIn("libgeos-dev", text)

    def test_static_files_are_collected_at_build_time_without_real_secrets(self):
        text = read("Dockerfile")
        self.assertIn("collectstatic --noinput", text)
        self.assertIn("SECRET_KEY=build-only", text)
        self.assertNotIn("COPY .env", text)

    def test_the_app_runs_as_a_non_root_user_after_the_build_steps(self):
        text = read("Dockerfile")
        users = [line.strip() for line in text.splitlines() if line.strip().startswith("USER ")]
        self.assertTrue(users)
        self.assertNotIn(users[-1], ("USER root", "USER 0"))
        self.assertLess(text.index("collectstatic"), text.index("USER spled"))

    def test_windows_line_endings_are_stripped_from_the_entrypoint(self):
        self.assertIn(r"sed -i 's/\r$//' docker/entrypoint.sh", read("Dockerfile"))

    def test_dockerignore_keeps_secrets_data_and_the_virtualenv_out(self):
        lines = {line.strip() for line in read(".dockerignore").splitlines()}
        for entry in (".env", ".env.*", "private_media/", "backups/", ".venv/", ".git/", "staticfiles/"):
            with self.subTest(entry=entry):
                self.assertIn(entry, lines)

    def test_entrypoint_migrates_then_hands_over_to_gunicorn(self):
        text = read("docker/entrypoint.sh")
        self.assertTrue(text.startswith("#!/bin/sh"))
        self.assertIn("set -e", text)
        self.assertIn("PORT", text)
        self.assertLess(text.index("migrate"), text.index("exec gunicorn"))

    def test_shell_scripts_keep_linux_line_endings_in_git(self):
        self.assertIn("*.sh text eol=lf", read(".gitattributes"))


class RenderBlueprintTests(SimpleTestCase):
    def setUp(self):
        self.text = read("render.yaml")
        self.blocks = env_blocks(self.text)
        self.assertTrue(
            self.blocks,
            "No '- key: NAME' entries were found in render.yaml. "
            "Check that its envVars list is present and indented as a YAML list.",
        )

    def test_it_is_a_docker_web_service_on_the_free_plan(self):
        for line in ("type: web", "runtime: docker", "plan: free"):
            with self.subTest(line=line):
                self.assertIn(line, self.text)

    def test_the_health_check_is_the_liveness_url_not_the_database_one(self):
        self.assertIn("healthCheckPath: /livez/", self.text)
        self.assertNotIn("healthCheckPath: /healthz", self.text)

    def test_secrets_are_asked_for_never_written_in_the_file(self):
        for key in ("DATABASE_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                    "R2_ENDPOINT_URL", "R2_PHOTO_BUCKET"):
            with self.subTest(key=key):
                self.assertIn("sync: false", self.blocks[key])
                self.assertFalse(any(line.startswith("value:") for line in self.blocks[key]))

    def test_the_secret_key_is_generated_by_the_host(self):
        self.assertEqual(self.blocks["SECRET_KEY"], ["generateValue: true"])

    def test_production_switches_are_set(self):
        expected = {
            "DEBUG": 'value: "False"',
            "BEHIND_PROXY": 'value: "True"',
            "PHOTO_STORAGE": "value: r2",
            "EMAIL_BACKEND": "value: django.core.mail.backends.console.EmailBackend",
        }
        for key, line in expected.items():
            with self.subTest(key=key):
                self.assertIn(line, self.blocks[key])

    def test_no_connection_string_is_hard_coded(self):
        self.assertNotIn("postgres://", self.text)
        self.assertNotIn("postgis://", self.text)