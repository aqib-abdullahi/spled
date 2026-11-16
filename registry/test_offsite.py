import base64
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

try:
    from registry import crypto, offsite
except ImportError:  # the cryptography package is not installed
    crypto = offsite = None

NEEDS_CRYPTO = unittest.skipIf(crypto is None, "cryptography is not installed")
KEY = crypto.generate_key() if crypto else ""
KEY_BYTES = b"k" * 32
PARTS = dict(host="db.example", port="5432", user="app", password="s3cret",
             dbname="spled", options={})


def encrypt(data, key=KEY_BYTES):
    out = io.BytesIO()
    crypto.encrypt_stream(io.BytesIO(data), out, key)
    return out.getvalue()


def decrypt(blob, key=KEY_BYTES):
    out = io.BytesIO()
    crypto.decrypt_stream(io.BytesIO(blob), out, key)
    return out.getvalue()


@NEEDS_CRYPTO
class CryptoTests(SimpleTestCase):
    def test_round_trip_over_several_chunks(self):
        data = bytes(range(100))
        with mock.patch.object(crypto, "CHUNK", 16):
            self.assertEqual(decrypt(encrypt(data)), data)

    def test_empty_data_round_trips(self):
        self.assertEqual(decrypt(encrypt(b"")), b"")

    def test_exact_multiple_of_the_chunk_size_has_no_extra_chunk(self):
        data = b"x" * 32
        with mock.patch.object(crypto, "CHUNK", 16):
            blob = encrypt(data)
            self.assertEqual(decrypt(blob), data)
        header = len(crypto.MAGIC) + crypto.PREFIX_LEN
        self.assertEqual(len(blob), header + 2 * (16 + crypto.TAG_LEN))

    def test_wrong_key_is_refused(self):
        with self.assertRaises(crypto.CryptoError):
            decrypt(encrypt(b"secret"), key=b"z" * 32)

    def test_flipped_byte_is_refused(self):
        blob = bytearray(encrypt(b"hello world"))
        blob[-1] ^= 1
        with self.assertRaises(crypto.CryptoError):
            decrypt(bytes(blob))

    def test_truncation_at_a_chunk_boundary_is_detected(self):
        with mock.patch.object(crypto, "CHUNK", 16):
            blob = encrypt(b"y" * 40)
            header = len(crypto.MAGIC) + crypto.PREFIX_LEN
            cut = blob[: header + 2 * (16 + crypto.TAG_LEN)]
            with self.assertRaises(crypto.CryptoError):
                decrypt(cut)

    def test_reordered_chunks_are_refused(self):
        with mock.patch.object(crypto, "CHUNK", 16):
            blob = encrypt(b"z" * 48)
            header = len(crypto.MAGIC) + crypto.PREFIX_LEN
            size = 16 + crypto.TAG_LEN
            c0, c1, c2 = (blob[header + i * size: header + (i + 1) * size] for i in range(3))
            swapped = blob[:header] + c1 + c0 + c2
            with self.assertRaises(crypto.CryptoError):
                decrypt(swapped)

    def test_a_file_in_another_format_is_refused(self):
        with self.assertRaises(crypto.CryptoError):
            decrypt(b"NOTOURS" + b"x" * 40)

    def test_same_data_encrypts_differently_each_time(self):
        self.assertNotEqual(encrypt(b"same"), encrypt(b"same"))

    def test_key_generation_and_validation(self):
        key = crypto.generate_key()
        self.assertEqual(len(crypto.parse_key(key)), 32)
        self.assertEqual(crypto.parse_key("  " + key + "\n"), crypto.parse_key(key))
        self.assertNotEqual(key, crypto.generate_key())
        for bad in ("", "   ", base64.urlsafe_b64encode(b"short").decode()):
            with self.subTest(bad=bad):
                with self.assertRaises(crypto.CryptoError):
                    crypto.parse_key(bad)

    def test_file_wrappers_round_trip_and_remove_partial_output(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "a").write_bytes(b"payload")
        crypto.encrypt_file(tmp / "a", tmp / "a.enc", KEY_BYTES)
        crypto.decrypt_file(tmp / "a.enc", tmp / "b", KEY_BYTES)
        self.assertEqual((tmp / "b").read_bytes(), b"payload")
        damaged = bytearray((tmp / "a.enc").read_bytes())
        damaged[-1] ^= 1
        (tmp / "bad.enc").write_bytes(bytes(damaged))
        with self.assertRaises(crypto.CryptoError):
            crypto.decrypt_file(tmp / "bad.enc", tmp / "c", KEY_BYTES)
        self.assertFalse((tmp / "c").exists())


GOOD = dict(
    R2_ENDPOINT_URL="https://acct.example.invalid", R2_BACKUP_ACCESS_KEY_ID="k",
    R2_BACKUP_SECRET_ACCESS_KEY="s", R2_BACKUP_BUCKET="backups", R2_PHOTO_BUCKET="photos",
)


@NEEDS_CRYPTO
class RemoteConfigTests(SimpleTestCase):
    @override_settings(R2_ENDPOINT_URL="", R2_BACKUP_ACCESS_KEY_ID="",
                       R2_BACKUP_SECRET_ACCESS_KEY="", R2_BACKUP_BUCKET="")
    def test_missing_settings_are_named(self):
        with self.assertRaises(CommandError) as ctx:
            offsite.remote_settings()
        self.assertIn("R2_BACKUP_BUCKET", str(ctx.exception))

    @override_settings(**{**GOOD, "R2_BACKUP_BUCKET": "photos"})
    def test_backups_cannot_share_the_photo_bucket(self):
        with self.assertRaises(CommandError) as ctx:
            offsite.remote_settings()
        self.assertIn("different bucket", str(ctx.exception))

    @override_settings(**{**GOOD, "R2_ENDPOINT_URL": "https://acct.example.invalid/backups"})
    def test_endpoint_with_a_path_is_refused(self):
        with self.assertRaises(CommandError):
            offsite.remote_settings()

    @unittest.skipUnless(importlib.util.find_spec("boto3"), "boto3 is not installed")
    @override_settings(**{**GOOD, "R2_BACKUP_ACCESS_KEY_ID": "key\n",
                          "R2_BACKUP_SECRET_ACCESS_KEY": " secret ",
                          "R2_BACKUP_BUCKET": "backups\r\n",
                          "R2_ENDPOINT_URL": "https://acct.example.invalid/"})
    def test_whitespace_is_cleaned_before_connecting(self):
        with mock.patch("boto3.client") as client:
            remote = offsite.get_remote()
        kwargs = client.call_args.kwargs
        self.assertEqual(kwargs["aws_access_key_id"], "key")
        self.assertEqual(kwargs["aws_secret_access_key"], "secret")
        self.assertEqual(kwargs["endpoint_url"], "https://acct.example.invalid")
        self.assertEqual(remote.bucket, "backups")


class FakeRemote:
    def __init__(self):
        self.objects, self.uploads = {}, []

    def upload(self, path, key):
        self.objects[key] = Path(path).read_bytes()
        self.uploads.append(key)

    def download(self, key, path):
        if key not in self.objects:
            raise FileNotFoundError(key)
        Path(path).write_bytes(self.objects[key])

    def exists(self, key):
        return key in self.objects

    def keys(self, prefix):
        return sorted(k for k in self.objects if k.startswith(prefix))


class FakeField:
    def __init__(self, data, error=None):
        self.data, self.error = data, error

    def open(self, mode):
        if self.error:
            raise self.error
        return io.BytesIO(self.data)


@NEEDS_CRYPTO
class OffsiteCommandTests(TestCase):
    def setUp(self):
        self.remote = FakeRemote()
        self.photos = []
        self.dump_bytes = b"dump-bytes"
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.enterContext(override_settings(BACKUP_ENCRYPTION_KEY=KEY, BACKUP_DIR=str(self.tmp / "local")))
        self.enterContext(mock.patch("registry.offsite.get_remote", return_value=self.remote))
        self.enterContext(mock.patch("registry.offsite.photo_rows", side_effect=lambda: iter(self.photos)))
        self.enterContext(mock.patch("registry.offsite.photo_hashes",
                                     side_effect=lambda: [p.sha256 for p in self.photos]))
        self.run_tool = mock.Mock(side_effect=self.fake_dump)
        self.enterContext(mock.patch("registry.backup.find_tool", return_value="pg_dump"))
        self.enterContext(mock.patch("registry.backup.connection_parts", return_value=PARTS))
        self.enterContext(mock.patch("registry.backup.run_tool", self.run_tool))

    def fake_dump(self, args, env):
        Path(args[args.index("--file") + 1]).write_bytes(self.dump_bytes)
        return ""

    def run(self, command, **options):
        out = io.StringIO()
        call_command(command, stdout=out, **options)
        return out.getvalue()

    def pull(self, **options):
        return self.run("backup_pull", output_dir=str(self.tmp / "restored"), **options)

    def add_photo(self, data=b"photo-bytes", error=None):
        photo = SimpleNamespace(
            id=len(self.photos) + 1, sha256=hashlib.sha256(data).hexdigest(),
            original=FakeField(data, error),
        )
        self.photos.append(photo)
        return photo

    def decrypt_object(self, key):
        return decrypt(self.remote.objects[key], key=crypto.parse_key(KEY))

    def two_pushes(self):
        with mock.patch("registry.backup.utc_stamp",
                        side_effect=["20260101T000000Z", "20260102T000000Z"]):
            self.run("backup_push", skip_photos=True)
            self.dump_bytes = b"second"
            self.run("backup_push", skip_photos=True)

    def test_push_uploads_the_dump_then_the_manifest(self):
        self.run("backup_push", skip_photos=True)
        self.assertEqual(len(self.remote.uploads), 2)
        self.assertTrue(self.remote.uploads[0].endswith(".dump.enc"))
        self.assertTrue(self.remote.uploads[1].endswith(".dump.json.enc"))

    def test_uploaded_files_are_encrypted_and_decrypt_to_the_original(self):
        self.run("backup_push", skip_photos=True)
        dump_key = [k for k in self.remote.objects if k.endswith(".dump.enc")][0]
        manifest_key = [k for k in self.remote.objects if k.endswith(".dump.json.enc")][0]
        self.assertEqual(self.decrypt_object(dump_key), b"dump-bytes")
        manifest = json.loads(self.decrypt_object(manifest_key))
        self.assertEqual(manifest["sha256"], hashlib.sha256(b"dump-bytes").hexdigest())
        self.assertIn("counts", manifest)
        for blob in self.remote.objects.values():
            self.assertNotIn(b"dump-bytes", blob)
        self.assertFalse((self.tmp / "local").exists())

    def test_push_without_a_key_stops_before_dumping(self):
        with override_settings(BACKUP_ENCRYPTION_KEY=""):
            with self.assertRaises(CommandError) as ctx:
                self.run("backup_push")
        self.assertIn("BACKUP_ENCRYPTION_KEY", str(ctx.exception))
        self.run_tool.assert_not_called()
        self.assertEqual(self.remote.uploads, [])

    def test_photos_are_encrypted_by_fingerprint_and_not_uploaded_twice(self):
        one, two = self.add_photo(b"one"), self.add_photo(b"two")
        self.run("backup_push")
        for photo, data in ((one, b"one"), (two, b"two")):
            key = f"photos/{photo.sha256}.enc"
            self.assertEqual(self.decrypt_object(key), data)
            self.assertNotIn(data, self.remote.objects[key])
        before = len(self.remote.uploads)
        out = self.run("backup_push")
        self.assertEqual(len(self.remote.uploads) - before, 2)  # only the database files
        self.assertIn("0 uploaded, 2 already backed up", out)

    def test_a_changed_photo_is_reported_and_never_uploaded(self):
        bad = self.add_photo(b"good")
        bad.sha256 = "0" * 64
        fine = self.add_photo(b"fine")
        with self.assertRaises(CommandError) as ctx:
            self.run("backup_push")
        self.assertIn("1 photo problem", str(ctx.exception))
        self.assertNotIn("photos/" + "0" * 64 + ".enc", self.remote.objects)
        self.assertIn(f"photos/{fine.sha256}.enc", self.remote.objects)
        self.assertTrue(any(k.endswith(".dump.enc") for k in self.remote.objects))

    def test_missing_and_unreadable_photos_are_told_apart(self):
        self.add_photo(b"a", error=FileNotFoundError())
        self.add_photo(b"b", error=RuntimeError("timeout"))
        out = io.StringIO()
        with self.assertRaises(CommandError):
            call_command("backup_push", stdout=out)
        text = out.getvalue()
        self.assertIn("photo 1 file missing", text)
        self.assertIn("photo 2 could not be read (RuntimeError)", text)

    def test_skip_photos_uploads_only_the_database(self):
        self.add_photo()
        self.run("backup_push", skip_photos=True)
        self.assertEqual(self.remote.keys("photos/"), [])

    def test_keep_local_leaves_the_plain_dump_in_the_backups_folder(self):
        self.run("backup_push", skip_photos=True, keep_local=True)
        local = self.tmp / "local"
        dumps = list(local.glob("spled-*.dump"))
        self.assertEqual(len(dumps), 1)
        self.assertTrue(Path(str(dumps[0]) + ".json").exists())

    def test_pull_fetches_the_latest_backup_and_it_checks_out(self):
        self.two_pushes()
        out = self.pull()
        restored = self.tmp / "restored"
        dump = restored / "spled-20260102T000000Z.dump"
        self.assertEqual(dump.read_bytes(), b"second")
        manifest = json.loads(Path(str(dump) + ".json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["sha256"], hashlib.sha256(b"second").hexdigest())
        self.assertIn("restore_drill", out)

    def test_pull_can_fetch_a_named_backup(self):
        self.two_pushes()
        self.pull(name="spled-20260101T000000Z.dump")
        self.assertEqual((self.tmp / "restored" / "spled-20260101T000000Z.dump").read_bytes(), b"dump-bytes")

    def test_pull_with_the_wrong_key_leaves_nothing_behind(self):
        self.run("backup_push", skip_photos=True)
        with override_settings(BACKUP_ENCRYPTION_KEY=crypto.generate_key()):
            with self.assertRaises(CommandError) as ctx:
                self.pull()
        self.assertIn("wrong key", str(ctx.exception))
        restored = self.tmp / "restored"
        self.assertEqual(list(restored.glob("*")) if restored.exists() else [], [])

    def test_pull_never_overwrites_an_existing_file(self):
        self.run("backup_push", skip_photos=True)
        self.pull()
        with self.assertRaises(CommandError) as ctx:
            self.pull()
        self.assertIn("already exists", str(ctx.exception))

    def test_check_passes_when_everything_is_backed_up(self):
        self.add_photo()
        self.run("backup_push")
        out = self.run("backup_check")
        self.assertIn("Photos: 1 of 1 backed up", out)
        self.assertIn("Off-site backups verified", out)

    def test_check_reports_a_photo_with_no_backup(self):
        self.add_photo()
        self.run("backup_push", skip_photos=True)
        with self.assertRaises(CommandError):
            out = io.StringIO()
            call_command("backup_check", stdout=out)
        self.assertIn("no backup of the photo", out.getvalue())

    def test_deep_check_catches_a_damaged_backup_copy(self):
        photo = self.add_photo()
        self.run("backup_push")
        key = f"photos/{photo.sha256}.enc"
        blob = bytearray(self.remote.objects[key])
        blob[-1] ^= 1
        self.remote.objects[key] = bytes(blob)
        self.run("backup_check")  # the object exists, so the quick check passes
        with self.assertRaises(CommandError):
            out = io.StringIO()
            call_command("backup_check", deep=True, stdout=out)
        self.assertIn("damaged", out.getvalue())

    def test_check_fails_when_the_newest_backup_is_too_old(self):
        with mock.patch("registry.backup.utc_stamp", return_value="20200101T000000Z"):
            self.run("backup_push", skip_photos=True)
        self.run("backup_check")  # no age limit given
        with self.assertRaises(CommandError):
            out = io.StringIO()
            call_command("backup_check", max_age_hours=24, stdout=out)
        self.assertIn("hours old", out.getvalue())

    def test_check_with_no_backups_fails(self):
        with self.assertRaises(CommandError) as ctx:
            self.run("backup_check")
        self.assertIn("no database backups", str(ctx.exception))

    def test_backup_key_prints_a_usable_key(self):
        first_line = self.run("backup_key").splitlines()[0]
        self.assertEqual(len(crypto.parse_key(first_line)), 32)