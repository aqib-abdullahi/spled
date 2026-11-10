import shutil
import tempfile
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, EvidencePhoto, EvidenceReview, Site
from registry.photos import process_image
from registry.testing import image_bytes

TMP = tempfile.mkdtemp()
NEAR = {"latitude": 9.0701, "longitude": 7.4001}
FAR = {"latitude": 9.5, "longitude": 7.9}


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def jpeg(name="a.jpg", color=(200, 30, 30)):
    return SimpleUploadedFile(name, image_bytes(color=color), content_type="image/jpeg")


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class PhotoUploadTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ("editor", "field", "contractor"):
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=role.title()
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        self.url = reverse("evidence_new", args=[self.site.pk])

    def post(self, role, photos=None, **extra):
        self.client.login(username=f"{role}@example.com", password="pw12345678")
        data = {
            "kind": "photo", "body": "Panels in", "tags": "",
            "latitude": NEAR["latitude"], "longitude": NEAR["longitude"],
            "new_status": "",
        }
        data.update(extra)
        if photos is not None:
            data["photos"] = photos
        return self.client.post(self.url, data)

    def test_field_user_can_attach_photos(self):
        r = self.post("field", [jpeg("a.jpg"), jpeg("b.jpg", (30, 200, 30))])
        self.assertRedirects(r, reverse("site_detail", args=[self.site.pk]))
        entry = EvidenceEntry.objects.get()
        self.assertEqual(entry.photos.count(), 2)
        self.assertEqual(
            sorted(entry.photo_hashes),
            sorted(entry.photos.values_list("sha256", flat=True)),
        )
        self.assertEqual(EvidenceEntry.verify_chain(self.site), [])

    def test_contractor_photo_entry_is_flagged_for_review(self):
        self.post("contractor", [jpeg()])
        entry = EvidenceEntry.objects.get()
        self.assertTrue(entry.needs_review)
        self.assertEqual(entry.photos.count(), 1)

    def test_non_image_is_rejected_and_nothing_is_saved(self):
        r = self.post("field", [SimpleUploadedFile("a.jpg", b"nope")])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 0)
        self.assertEqual(EvidencePhoto.objects.count(), 0)

    def test_photo_entry_needs_a_photo(self):
        r = self.post("field", None)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 0)

    def test_too_many_photos_are_rejected(self):
        r = self.post("field", [jpeg(f"{i}.jpg") for i in range(6)])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 0)

    def test_refused_status_change_saves_no_entry_and_no_photos(self):
        r = self.post(
            "editor", [jpeg()], kind="note", new_status="delayed", **FAR
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 0)
        self.assertEqual(EvidencePhoto.objects.count(), 0)


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class PhotoServingTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.editor = User.objects.create_user("editor@example.com", "pw12345678", full_name="Editor")
        self.crew = User.objects.create_user("crew@example.com", "pw12345678", full_name="Crew")
        Membership.objects.create(user=self.editor, organisation=self.org, role="editor")
        Membership.objects.create(user=self.crew, organisation=self.org, role="contractor")
        other_org = Organisation.objects.create(
            name="Other", kind="private", verification="verified"
        )
        self.outsider = User.objects.create_user("out@example.com", "pw12345678", full_name="Out")
        Membership.objects.create(user=self.outsider, organisation=other_org, role="admin")
        self.site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )

    def make_photo(self, needs_review=False):
        processed = process_image(SimpleUploadedFile("a.jpg", image_bytes()))
        entry = EvidenceEntry.objects.create(
            site=self.site, author=self.crew, kind="photo", body="Trench",
            needs_review=needs_review, photo_hashes=[processed.sha256],
        )
        self.entry = entry
        self.photo = EvidencePhoto.create_from(entry, processed)
        return self.photo

    def url(self, variant="thumb"):
        return reverse("photo", args=[self.photo.pk, variant])

    def publish(self):
        Site.objects.filter(pk=self.site.pk).update(is_public=True)

    def login(self, who):
        self.client.login(username=f"{who}@example.com", password="pw12345678")

    def test_organisation_member_can_see_the_photo(self):
        self.make_photo()
        self.login("editor")
        for variant in ("thumb", "display"):
            r = self.client.get(self.url(variant))
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Content-Type"], "image/jpeg")
            self.assertIn("private", r["Cache-Control"])

    def test_member_of_another_organisation_gets_404(self):
        self.make_photo()
        self.login("out")
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_anonymous_gets_404_for_a_private_site(self):
        self.make_photo()
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_the_original_is_never_served(self):
        self.make_photo()
        self.publish()
        self.login("editor")
        self.assertEqual(self.client.get(self.url("original")).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url("original")).status_code, 404)

    def test_counted_photo_on_a_public_site_is_visible_to_anyone(self):
        self.make_photo()
        self.publish()
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)

    def test_pending_contractor_photo_is_not_public_but_staff_can_see_it(self):
        self.make_photo(needs_review=True)
        self.publish()
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.login("editor")
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)

    def test_approved_contractor_photo_becomes_public(self):
        self.make_photo(needs_review=True)
        self.publish()
        EvidenceReview.objects.create(
            entry=self.entry, reviewer=self.editor, decision="approved"
        )
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)

    def test_unpublishing_hides_the_photo(self):
        self.make_photo()
        self.publish()
        Site.objects.filter(pk=self.site.pk).update(is_public=False)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_public_page_links_to_the_photo_but_not_the_original(self):
        self.make_photo()
        self.publish()
        page = self.client.get(reverse("project", args=[self.site.pk]))
        self.assertContains(page, self.url("thumb"))
        self.assertNotContains(page, self.photo.original.name)

    def test_missing_file_gives_404(self):
        self.make_photo()
        Path(self.photo.thumb.path).unlink()
        self.login("editor")
        self.assertEqual(self.client.get(self.url("thumb")).status_code, 404)