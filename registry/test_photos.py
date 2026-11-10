import hashlib
import io
import shutil
import tempfile
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase, override_settings
from PIL import Image

from accounts.models import User
from organisations.models import Organisation

from .models import EvidenceEntry, EvidencePhoto, Site
from .photos import MAX_BYTES, PhotoError, process_image
from .testing import image_bytes

TMP = tempfile.mkdtemp()


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def upload(data, name="a.jpg"):
    return SimpleUploadedFile(name, data)


class ProcessingTests(TestCase):
    def test_valid_jpeg_is_resized_and_fingerprinted(self):
        data = image_bytes(size=(2400, 1600))
        p = process_image(upload(data))
        self.assertEqual(p.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(p.original, data)
        self.assertEqual(max(Image.open(io.BytesIO(p.display)).size), 1600)
        self.assertLessEqual(max(Image.open(io.BytesIO(p.thumb)).size), 480)
        self.assertEqual((p.width, p.height), (2400, 1600))

    def test_exif_is_removed_and_orientation_applied(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 degrees
        exif[0x010F] = "TestCam"  # camera make
        data = image_bytes(size=(200, 100), exif=exif)
        self.assertTrue(Image.open(io.BytesIO(data)).getexif())
        p = process_image(upload(data))
        self.assertEqual((p.width, p.height), (100, 200))
        self.assertEqual(len(Image.open(io.BytesIO(p.display)).getexif()), 0)
        self.assertEqual(len(Image.open(io.BytesIO(p.thumb)).getexif()), 0)

    def test_transparent_png_is_flattened_to_jpeg(self):
        p = process_image(upload(image_bytes("PNG", mode="RGBA"), "a.png"))
        shown = Image.open(io.BytesIO(p.display))
        self.assertEqual((shown.format, shown.mode), ("JPEG", "RGB"))
        self.assertEqual(p.ext, "png")

    def test_non_image_is_rejected(self):
        with self.assertRaises(PhotoError):
            process_image(upload(b"this is not an image at all"))

    def test_unsupported_format_is_rejected(self):
        with self.assertRaises(PhotoError):
            process_image(upload(image_bytes("GIF"), "a.gif"))

    def test_oversized_file_is_rejected(self):
        with self.assertRaises(PhotoError):
            process_image(upload(b"x" * (MAX_BYTES + 1)))

    def test_empty_file_is_rejected(self):
        with self.assertRaises(PhotoError):
            process_image(upload(b""))


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class PhotoModelTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Org", kind="government", verification="verified"
        )
        self.user = User.objects.create_user("p@example.com", "pw12345678", full_name="P")
        self.site = Site.objects.create(
            organisation=self.org, name="S", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )

    def add(self, count=1):
        processed = [
            process_image(upload(image_bytes(color=(10 + i * 40, 50, 50)), f"{i}.jpg"))
            for i in range(count)
        ]
        entry = EvidenceEntry.objects.create(
            site=self.site, author=self.user, kind="photo", body="x",
            photo_hashes=[p.sha256 for p in processed],
        )
        return entry, [EvidencePhoto.create_from(entry, p) for p in processed]

    def test_photo_fingerprints_are_part_of_the_chain(self):
        entry, _ = self.add()
        self.assertEqual(EvidenceEntry.verify_chain(self.site), [])
        entry.photo_hashes = []
        self.assertNotEqual(entry.compute_hash(), entry.content_hash)

    def test_chain_detects_a_swapped_photo_record(self):
        entry, (photo,) = self.add()
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "ALTER TABLE registry_evidencephoto DISABLE TRIGGER photo_no_update_delete"
            )
            cursor.execute(
                "UPDATE registry_evidencephoto SET sha256 = %s WHERE id = %s",
                ["0" * 64, photo.id],
            )
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "ALTER TABLE registry_evidencephoto ENABLE TRIGGER photo_no_update_delete"
            )
        self.assertIn(
            (entry.id, "photos changed"), EvidenceEntry.verify_chain(self.site)
        )

    def test_photo_rows_cannot_be_changed_or_deleted(self):
        _, (photo,) = self.add()
        photo.sha256 = "x"
        with self.assertRaises(PermissionError):
            photo.save()
        with self.assertRaises(PermissionError):
            photo.delete()
        with self.assertRaises(PermissionError):
            EvidencePhoto.objects.all().delete()
        with self.assertRaises(PermissionError):
            EvidencePhoto.objects.all().update(sha256="x")

    def test_database_refuses_raw_photo_changes(self):
        self.add()
        for sql in (
            "UPDATE registry_evidencephoto SET sha256 = 'x'",
            "DELETE FROM registry_evidencephoto",
            "TRUNCATE registry_evidencephoto",
        ):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql)

    def test_verify_files_detects_a_changed_and_a_missing_file(self):
        entry, (photo,) = self.add()
        self.assertEqual(EvidenceEntry.verify_files(self.site), [])
        path = Path(photo.original.path)
        path.write_bytes(b"changed")
        self.assertIn(
            (entry.id, f"photo {photo.id} file changed"),
            EvidenceEntry.verify_files(self.site),
        )
        path.unlink()
        self.assertIn(
            (entry.id, f"photo {photo.id} file missing"),
            EvidenceEntry.verify_files(self.site),
        )

    def test_check_evidence_command(self):
        _, (photo,) = self.add()
        call_command("check_evidence", stdout=io.StringIO())
        Path(photo.original.path).write_bytes(b"changed")
        with self.assertRaises(CommandError):
            call_command("check_evidence", stdout=io.StringIO())