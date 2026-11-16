import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from registry.photos import (
    PrivateStorage,
    build_private_storage,
    check_photo_file,
    check_photo_storage,
)

import hashlib

R2 = dict(
    PHOTO_STORAGE="r2",
    R2_ENDPOINT_URL="https://example.invalid",
    R2_ACCESS_KEY_ID="key",
    R2_SECRET_ACCESS_KEY="secret",
    R2_PHOTO_BUCKET="bucket",
)


class FakeField:
    def __init__(self, data=None, error=None):
        self.data, self.error = data, error

    def open(self, mode):
        if self.error:
            raise self.error
        return io.BytesIO(self.data)


def fake_photo(data=b"abc", error=None, sha=None):
    return SimpleNamespace(
        id=7,
        original=FakeField(data, error),
        sha256=sha or hashlib.sha256(b"abc").hexdigest(),
    )


class CheckPhotoFileTests(SimpleTestCase):
    def test_matching_file_has_no_problem(self):
        self.assertIsNone(check_photo_file(fake_photo()))

    def test_changed_file_is_reported(self):
        self.assertEqual(check_photo_file(fake_photo(data=b"abd")), "photo 7 file changed")

    def test_missing_file_is_reported_as_missing(self):
        self.assertEqual(
            check_photo_file(fake_photo(error=FileNotFoundError())), "photo 7 file missing"
        )

    def test_storage_trouble_is_not_called_missing(self):
        result = check_photo_file(fake_photo(error=RuntimeError("timeout")))
        self.assertEqual(result, "photo 7 could not be read (RuntimeError)")

    def test_file_without_a_name_is_reported(self):
        result = check_photo_file(fake_photo(error=ValueError("no file")))
        self.assertEqual(result, "photo 7 could not be read (ValueError)")


class BuildStorageTests(SimpleTestCase):
    @override_settings(PHOTO_STORAGE="local")
    def test_local_is_the_default(self):
        self.assertIsInstance(build_private_storage(), PrivateStorage)

    @override_settings(PHOTO_STORAGE="floppy")
    def test_unknown_backend_is_refused(self):
        with self.assertRaises(ImproperlyConfigured):
            build_private_storage()

    @override_settings(
        PHOTO_STORAGE="r2", R2_ENDPOINT_URL="", R2_ACCESS_KEY_ID="",
        R2_SECRET_ACCESS_KEY="", R2_PHOTO_BUCKET="",
    )
    def test_r2_without_settings_names_what_is_missing(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            build_private_storage()
        self.assertIn("R2_PHOTO_BUCKET", str(ctx.exception))

    @override_settings(**R2)
    def test_r2_without_the_library_says_how_to_install_it(self):
        blocked = {"storages": None, "storages.backends": None, "storages.backends.s3": None}
        with mock.patch.dict(sys.modules, blocked):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                build_private_storage()
        self.assertIn("requirements-prod.txt", str(ctx.exception))

    @unittest.skipUnless(importlib.util.find_spec("storages"), "django-storages is not installed")
    @override_settings(**R2)
    def test_r2_with_settings_builds_an_s3_storage(self):
        storage = build_private_storage()
        self.assertEqual(storage.bucket_name, "bucket")
        self.assertEqual(storage.endpoint_url, "https://example.invalid")

    def test_tests_never_use_a_real_bucket(self):
        self.assertEqual(settings.PHOTO_STORAGE, "local")


class DeployCheckTests(SimpleTestCase):
    @override_settings(DEBUG=False, PHOTO_STORAGE="local")
    def test_warns_about_local_photos_in_production(self):
        found = check_photo_storage(None)
        self.assertEqual([w.id for w in found], ["spled.W001"])

    @override_settings(DEBUG=True, PHOTO_STORAGE="local")
    def test_quiet_in_development(self):
        self.assertEqual(check_photo_storage(None), [])

    @override_settings(DEBUG=False, PHOTO_STORAGE="r2")
    def test_quiet_when_photos_are_in_a_bucket(self):
        self.assertEqual(check_photo_storage(None), [])
        
    @override_settings(DEBUG=True, PHOTO_STORAGE="local")
    def test_works_when_django_passes_keyword_arguments(self):
        # `manage.py check` calls every check like this
        self.assertEqual(check_photo_storage(app_configs=None, databases=["default"]), [])
        
    @override_settings(DEBUG=False, PHOTO_STORAGE="local", PHOTOS_ON_PERSISTENT_DISK=True)
    def test_quiet_when_local_disk_is_acknowledged(self):
        self.assertEqual(check_photo_storage(app_configs=None), [])

    @override_settings(DEBUG=False, PHOTO_STORAGE="local", PHOTOS_ON_PERSISTENT_DISK=False)
    def test_still_warns_when_local_disk_is_not_acknowledged(self):
        self.assertEqual([w.id for w in check_photo_storage(app_configs=None)], ["spled.W001"])

    def test_acknowledgement_is_off_by_default(self):
        self.assertFalse(settings.PHOTOS_ON_PERSISTENT_DISK)

class StubStorage:
    def __init__(self, read_back=None, fail=False):
        self.read_back, self.fail = read_back, fail
        self.payload, self.deleted = None, []

    def save(self, name, content):
        if self.fail:
            raise RuntimeError("boom")
        self.payload = content.read()
        return name

    def open(self, name, mode):
        return io.BytesIO(self.payload if self.read_back is None else self.read_back)

    def delete(self, name):
        self.deleted.append(name)


class CheckStorageCommandTests(TestCase):
    def run_command(self):
        out = io.StringIO()
        call_command("check_storage", stdout=out)
        return out.getvalue()

    def test_writes_reads_and_deletes_on_local_storage(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with override_settings(PRIVATE_MEDIA_ROOT=tmp):
            output = self.run_command()
        self.assertIn("Photo storage works", output)
        folder = os.path.join(tmp, "healthcheck")
        self.assertEqual(os.listdir(folder) if os.path.isdir(folder) else [], [])

    def test_different_data_is_an_error_and_the_test_file_is_still_removed(self):
        stub = StubStorage(read_back=b"different")
        with mock.patch("registry.management.commands.check_storage.private_storage", return_value=stub):
            with self.assertRaises(CommandError):
                self.run_command()
        self.assertEqual(len(stub.deleted), 1)

    def test_storage_errors_become_a_command_error(self):
        stub = StubStorage(fail=True)
        with mock.patch("registry.management.commands.check_storage.private_storage", return_value=stub):
            with self.assertRaises(CommandError) as ctx:
                self.run_command()
        self.assertIn("RuntimeError", str(ctx.exception))
        self.assertEqual(stub.deleted, [])


class WiringTests(SimpleTestCase):
    def test_verify_files_uses_the_shared_check(self):
        text = (Path(__file__).resolve().parent / "models.py").read_text(encoding="utf-8")
        self.assertIn("check_photo_file(photo)", text)
        self.assertNotIn("except OSError", text)

class R2SettingsCleanupTests(SimpleTestCase):
    @unittest.skipUnless(importlib.util.find_spec("storages"), "django-storages is not installed")
    @override_settings(
        PHOTO_STORAGE="r2", R2_ENDPOINT_URL="https://example.invalid/",
        R2_ACCESS_KEY_ID="key\n", R2_SECRET_ACCESS_KEY=" secret ", R2_PHOTO_BUCKET="bucket\r\n",
    )
    def test_stray_whitespace_is_removed_before_signing(self):
        with mock.patch("storages.backends.s3.S3Storage") as s3:
            build_private_storage()
        kwargs = s3.call_args.kwargs
        self.assertEqual(kwargs["access_key"], "key")
        self.assertEqual(kwargs["secret_key"], "secret")
        self.assertEqual(kwargs["bucket_name"], "bucket")
        self.assertEqual(kwargs["endpoint_url"], "https://example.invalid")

    @override_settings(
        PHOTO_STORAGE="r2", R2_ENDPOINT_URL="https://example.invalid",
        R2_ACCESS_KEY_ID="  \n", R2_SECRET_ACCESS_KEY="secret", R2_PHOTO_BUCKET="bucket",
    )
    def test_a_value_that_is_only_whitespace_counts_as_missing(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            build_private_storage()
        self.assertIn("R2_ACCESS_KEY_ID", str(ctx.exception))

    @override_settings(
        PHOTO_STORAGE="r2", R2_ENDPOINT_URL="https://example.invalid/spled",
        R2_ACCESS_KEY_ID="key", R2_SECRET_ACCESS_KEY="secret", R2_PHOTO_BUCKET="spled",
    )
    def test_bucket_name_in_the_endpoint_is_refused(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            build_private_storage()
        self.assertIn("R2_PHOTO_BUCKET", str(ctx.exception))

    @override_settings(
        PHOTO_STORAGE="r2", R2_ENDPOINT_URL="http://example.invalid",
        R2_ACCESS_KEY_ID="key", R2_SECRET_ACCESS_KEY="secret", R2_PHOTO_BUCKET="bucket",
    )
    def test_plain_http_endpoint_is_refused(self):
        with self.assertRaises(ImproperlyConfigured):
            build_private_storage()