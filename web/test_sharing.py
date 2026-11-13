import json
import shutil
import tempfile
from datetime import timedelta

from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, EvidencePhoto, Milestone, Site
from registry.photos import process_image
from registry.testing import image_bytes
from sharing.models import MAX_ACTIVE_PER_SITE, MAX_FAILED, ShareLink

TMP = tempfile.mkdtemp()
ROLES = ("admin", "editor", "owner", "field", "viewer", "contractor")
DENIED = ("field", "viewer", "contractor")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def make_site(org, name, **kwargs):
    return Site.objects.create(
        organisation=org, name=name, kind="road",
        location=Point(7.4, 9.07, srid=4326), **kwargs,
    )


class ShareBase(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ROLES:
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=f"Zed {role.title()}"
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.site = make_site(self.org, "Riverside")
        Milestone.objects.create(site=self.site, title="Site survey")
        self.entry = EvidenceEntry.objects.create(
            site=self.site, author=self.users["editor"], kind="note",
            body="Poured foundations", location=Point(7.4001, 9.0701, srid=4326),
        )
        EvidenceEntry.objects.create(
            site=self.site, author=self.users["contractor"], kind="note",
            body="Trench pending", needs_review=True,
        )
        other_org = Organisation.objects.create(
            name="Other", kind="private", verification="verified"
        )
        self.theirs = make_site(other_org, "Theirs")
        self.other_site = make_site(self.org, "Other Road")
        EvidenceEntry.objects.create(
            site=self.other_site, author=self.users["editor"], kind="note",
            body="Elsewhere entry",
        )

    def login(self, role="editor"):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def make_link(self, site=None, **kwargs):
        kwargs.setdefault("label", "Investors")
        return ShareLink.create_for(site or self.site, created_by=self.users["editor"], **kwargs)

    def url(self, raw):
        return reverse("share_view", args=[raw])


class ShareManageTests(ShareBase):
    def page(self, site=None):
        return reverse("share_links", args=[(site or self.site).pk])

    def create_url(self, site=None):
        return reverse("share_create", args=[(site or self.site).pk])

    def data(self, **extra):
        d = {
            "label": "Investors", "days": 30,
            "include_photos": "on", "include_milestones": "on", "password": "",
        }
        d.update(extra)
        return {k: v for k, v in d.items() if v is not None}

    def test_page_needs_sign_in(self):
        self.assertEqual(self.client.get(self.page()).status_code, 302)

    def test_who_can_manage_links(self):
        for role in ("admin", "editor", "owner"):
            self.login(role)
            self.assertEqual(self.client.get(self.page()).status_code, 200, role)
        for role in DENIED:
            self.login(role)
            self.assertEqual(self.client.get(self.page()).status_code, 403, role)

    def test_creating_a_link_shows_the_url_once(self):
        self.login("editor")
        r = self.client.post(self.create_url(), self.data(), follow=True)
        self.assertContains(r, "Copy it now")
        raw = r.context["new_link"]["url"].rstrip("/").rsplit("/", 1)[-1]
        link = ShareLink.objects.get()
        self.assertEqual(ShareLink.lookup(raw), link)
        self.assertEqual(link.label, "Investors")
        self.assertEqual(link.created_by, self.users["editor"])
        self.assertFalse(link.has_password)
        again = self.client.get(self.page())
        self.assertNotContains(again, "Copy it now")
        self.assertNotContains(again, raw)

    def test_creation_is_logged_without_the_token(self):
        self.login("editor")
        r = self.client.post(self.create_url(), self.data(), follow=True)
        raw = r.context["new_link"]["url"].rstrip("/").rsplit("/", 1)[-1]
        event = AuditEvent.objects.get(action="share.created")
        self.assertEqual(event.detail["label"], "Investors")
        self.assertEqual(event.target_id, self.site.pk)
        self.assertNotIn(raw, json.dumps(event.detail))
        self.assertNotIn(raw, event.target_label)

    def test_a_label_is_required(self):
        self.login("editor")
        r = self.client.post(self.create_url(), self.data(label=""))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ShareLink.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_an_unknown_expiry_is_refused(self):
        self.login("editor")
        r = self.client.post(self.create_url(), self.data(days=1000))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ShareLink.objects.count(), 0)

    def test_a_short_password_is_refused(self):
        self.login("editor")
        r = self.client.post(self.create_url(), self.data(password="abc"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ShareLink.objects.count(), 0)

    def test_a_password_can_be_set(self):
        self.login("editor")
        self.client.post(self.create_url(), self.data(password="correct horse battery"))
        link = ShareLink.objects.get()
        self.assertTrue(link.has_password)
        self.assertNotEqual(link.password_hash, "correct horse battery")

    def test_options_can_be_switched_off(self):
        self.login("editor")
        self.client.post(
            self.create_url(), self.data(include_photos=None, include_milestones=None)
        )
        link = ShareLink.objects.get()
        self.assertFalse(link.include_photos)
        self.assertFalse(link.include_milestones)

    def test_non_managers_cannot_create_or_revoke(self):
        link, _ = self.make_link()
        for role in DENIED:
            self.login(role)
            self.assertEqual(
                self.client.post(self.create_url(), self.data()).status_code, 403, role
            )
            revoke = reverse("share_revoke", args=[self.site.pk, link.pk])
            self.assertEqual(self.client.post(revoke).status_code, 403, role)
        self.assertEqual(ShareLink.objects.count(), 1)
        link.refresh_from_db()
        self.assertIsNone(link.revoked_at)

    def test_another_organisations_site_is_404(self):
        self.login("editor")
        self.assertEqual(self.client.get(self.page(self.theirs)).status_code, 404)
        r = self.client.post(self.create_url(self.theirs), self.data())
        self.assertEqual(r.status_code, 404)
        self.assertEqual(ShareLink.objects.count(), 0)

    def test_revoking_a_link(self):
        link, _ = self.make_link()
        self.login("editor")
        url = reverse("share_revoke", args=[self.site.pk, link.pk])
        self.assertRedirects(self.client.post(url), self.page())
        link.refresh_from_db()
        self.assertIsNotNone(link.revoked_at)
        self.assertEqual(AuditEvent.objects.get().action, "share.revoked")
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_a_link_cannot_be_revoked_through_another_site(self):
        link, _ = self.make_link()
        self.login("editor")
        url = reverse("share_revoke", args=[self.other_site.pk, link.pk])
        self.assertEqual(self.client.post(url).status_code, 404)
        link.refresh_from_db()
        self.assertIsNone(link.revoked_at)

    def test_the_active_link_cap(self):
        for _ in range(MAX_ACTIVE_PER_SITE):
            self.make_link()
        self.login("editor")
        r = self.client.post(self.create_url(), self.data())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "at most")
        self.assertEqual(ShareLink.objects.count(), MAX_ACTIVE_PER_SITE)

    def test_revoked_links_do_not_count_towards_the_cap(self):
        for _ in range(MAX_ACTIVE_PER_SITE):
            self.make_link()
        ShareLink.objects.update(revoked_at=timezone.now())
        self.login("editor")
        self.assertRedirects(self.client.post(self.create_url(), self.data()), self.page())
        self.assertEqual(ShareLink.objects.count(), MAX_ACTIVE_PER_SITE + 1)

    def test_the_list_shows_links_and_their_state(self):
        active, _ = self.make_link(label="Active one")
        revoked, _ = self.make_link(label="Revoked one")
        ShareLink.objects.filter(pk=revoked.pk).update(revoked_at=timezone.now())
        ShareLink.objects.filter(pk=active.pk).update(view_count=3)
        self.login("editor")
        r = self.client.get(self.page())
        self.assertContains(r, "Active one")
        self.assertContains(r, "Revoked one")
        self.assertContains(r, "Revoked")
        self.assertContains(r, "3 view")
        self.assertContains(r, reverse("share_revoke", args=[self.site.pk, active.pk]))
        self.assertNotContains(r, reverse("share_revoke", args=[self.site.pk, revoked.pk]))

    def test_creation_only_accepts_post(self):
        self.login("editor")
        self.assertEqual(self.client.get(self.create_url()).status_code, 405)

    def test_the_share_button_follows_the_permission(self):
        share = reverse("share_links", args=[self.site.pk])
        self.login("editor")
        self.assertContains(self.client.get(reverse("site_detail", args=[self.site.pk])), share)
        self.login("field")
        self.assertNotContains(self.client.get(reverse("site_detail", args=[self.site.pk])), share)

    def test_creation_and_revocation_show_in_the_audit_log(self):
        self.login("editor")
        self.client.post(self.create_url(), self.data())
        self.login("admin")
        self.assertContains(self.client.get(reverse("audit_log")), "Share link created")


class ShareViewTests(ShareBase):
    def test_an_active_link_shows_the_site_without_signing_in(self):
        _, raw = self.make_link()
        r = self.client.get(self.url(raw))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Riverside")
        self.assertContains(r, "Poured foundations")
        self.assertContains(r, "Read-only view")

    def test_an_unknown_link_is_404(self):
        self.assertEqual(self.client.get(self.url("nope")).status_code, 404)

    def test_an_expired_link_is_gone(self):
        link, raw = self.make_link()
        ShareLink.objects.filter(pk=link.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        r = self.client.get(self.url(raw))
        self.assertContains(r, "isn’t available", status_code=410)
        self.assertNotContains(r, "Riverside", status_code=410)

    def test_a_revoked_link_is_gone(self):
        link, raw = self.make_link()
        ShareLink.objects.filter(pk=link.pk).update(revoked_at=timezone.now())
        self.assertEqual(self.client.get(self.url(raw)).status_code, 410)

    def test_a_link_to_an_archived_site_is_gone(self):
        _, raw = self.make_link()
        self.site.archive()
        self.assertEqual(self.client.get(self.url(raw)).status_code, 410)

    def test_only_counted_entries_are_shown(self):
        _, raw = self.make_link()
        r = self.client.get(self.url(raw))
        self.assertContains(r, "Poured foundations")
        self.assertNotContains(r, "Trench pending")

    def test_staff_names_and_emails_never_appear(self):
        _, raw = self.make_link()
        r = self.client.get(self.url(raw))
        self.assertNotContains(r, "Zed")
        self.assertNotContains(r, "@example.com")
        self.assertContains(r, "project team")

    def test_milestones_can_be_left_out(self):
        _, on = self.make_link(label="a")
        _, off = self.make_link(label="b", include_milestones=False)
        self.assertContains(self.client.get(self.url(on)), "Site survey")
        self.assertNotContains(self.client.get(self.url(off)), "Site survey")

    def test_only_the_shared_site_is_shown(self):
        _, raw = self.make_link()
        r = self.client.get(self.url(raw))
        self.assertNotContains(r, "Other Road")
        self.assertNotContains(r, "Elsewhere entry")

    def test_views_are_counted(self):
        link, raw = self.make_link()
        self.client.get(self.url(raw))
        self.client.get(self.url(raw))
        link.refresh_from_db()
        self.assertEqual(link.view_count, 2)
        self.assertIsNotNone(link.last_viewed_at)

    def test_search_engines_and_caches_are_told_to_stay_away(self):
        _, raw = self.make_link()
        r = self.client.get(self.url(raw))
        self.assertIn("noindex", r["X-Robots-Tag"])
        self.assertIn("no-store", r["Cache-Control"])

    def test_the_page_does_not_link_to_staff_pages(self):
        _, raw = self.make_link()
        self.assertNotContains(self.client.get(self.url(raw)), "/app/")

    def test_a_link_does_not_make_the_site_public(self):
        self.make_link()
        r = self.client.get(reverse("project", args=[self.site.pk]))
        self.assertEqual(r.status_code, 404)

    def test_changes_show_up_live(self):
        _, raw = self.make_link()
        self.assertNotContains(self.client.get(self.url(raw)), "Added later")
        EvidenceEntry.objects.create(
            site=self.site, author=self.users["editor"], kind="note", body="Added later"
        )
        self.assertContains(self.client.get(self.url(raw)), "Added later")

    def test_corrections_are_shown_with_their_reason(self):
        EvidenceEntry.objects.create(
            site=self.site, author=self.users["editor"], kind="note",
            body="Poured rows 1 and 2", amends=self.entry,
            amendment_reason="Entered in error",
        )
        _, raw = self.make_link()
        r = self.client.get(self.url(raw))
        self.assertContains(r, "Entered in error")
        self.assertContains(r, "Correction")

    def test_a_post_to_an_open_link_is_refused(self):
        _, raw = self.make_link()
        self.assertEqual(self.client.post(self.url(raw)).status_code, 405)


class SharePasswordTests(ShareBase):
    def test_a_protected_link_asks_for_the_password_first(self):
        _, raw = self.make_link(password="correct horse")
        r = self.client.get(self.url(raw))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Enter the password")
        self.assertNotContains(r, "Riverside")
        self.assertNotContains(r, "Poured foundations")

    def test_a_wrong_password_is_refused(self):
        _, raw = self.make_link(password="correct horse")
        r = self.client.post(self.url(raw), {"password": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "isn’t right")
        self.assertNotContains(r, "Riverside")

    def test_the_right_password_unlocks_this_browser_only(self):
        _, raw = self.make_link(password="correct horse")
        r = self.client.post(self.url(raw), {"password": "correct horse"})
        self.assertRedirects(r, self.url(raw))
        self.assertContains(self.client.get(self.url(raw)), "Riverside")
        stranger = self.client_class()
        self.assertContains(stranger.get(self.url(raw)), "Enter the password")

    def test_too_many_wrong_passwords_lock_the_link(self):
        _, raw = self.make_link(password="correct horse")
        for _ in range(MAX_FAILED - 1):
            self.assertEqual(
                self.client.post(self.url(raw), {"password": "nope"}).status_code, 200
            )
        self.assertEqual(self.client.post(self.url(raw), {"password": "nope"}).status_code, 429)
        r = self.client.post(self.url(raw), {"password": "correct horse"})
        self.assertEqual(r.status_code, 429)
        self.assertNotContains(r, "Riverside", status_code=429)

    def test_views_are_not_counted_before_unlocking(self):
        link, raw = self.make_link(password="correct horse")
        self.client.get(self.url(raw))
        self.client.post(self.url(raw), {"password": "nope"})
        link.refresh_from_db()
        self.assertEqual(link.view_count, 0)
        self.client.post(self.url(raw), {"password": "correct horse"})
        self.client.get(self.url(raw))
        link.refresh_from_db()
        self.assertEqual(link.view_count, 1)


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class SharePhotoTests(ShareBase):
    def make_photo(self, site=None, needs_review=False):
        processed = process_image(SimpleUploadedFile("a.jpg", image_bytes()))
        entry = EvidenceEntry.objects.create(
            site=site or self.site, author=self.users["field"], kind="photo",
            body="Photo entry", needs_review=needs_review,
            photo_hashes=[processed.sha256],
        )
        return EvidencePhoto.create_from(entry, processed)

    def photo_url(self, raw, photo, variant="thumb"):
        return reverse("share_photo", args=[raw, photo.pk, variant])

    def test_photos_are_served_through_the_link(self):
        _, raw = self.make_link()
        photo = self.make_photo()
        r = self.client.get(self.photo_url(raw, photo))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/jpeg")
        self.assertIn("no-store", r["Cache-Control"])
        page = self.client.get(self.url(raw))
        self.assertContains(page, self.photo_url(raw, photo))
        self.assertNotContains(page, '"' + reverse("photo", args=[photo.pk, "thumb"]) + '"')

    def test_photos_can_be_left_out(self):
        _, raw = self.make_link(include_photos=False)
        photo = self.make_photo()
        self.assertNotContains(self.client.get(self.url(raw)), "/photos/")
        self.assertEqual(self.client.get(self.photo_url(raw, photo)).status_code, 404)

    def test_pending_photos_are_not_served(self):
        _, raw = self.make_link()
        photo = self.make_photo(needs_review=True)
        self.assertEqual(self.client.get(self.photo_url(raw, photo)).status_code, 404)

    def test_photos_of_other_sites_are_not_served(self):
        _, raw = self.make_link()
        photo = self.make_photo(site=self.other_site)
        self.assertEqual(self.client.get(self.photo_url(raw, photo)).status_code, 404)

    def test_the_original_is_never_served(self):
        _, raw = self.make_link()
        photo = self.make_photo()
        self.assertEqual(self.client.get(self.photo_url(raw, photo, "original")).status_code, 404)

    def test_revoked_links_stop_serving_photos(self):
        link, raw = self.make_link()
        photo = self.make_photo()
        ShareLink.objects.filter(pk=link.pk).update(revoked_at=timezone.now())
        self.assertEqual(self.client.get(self.photo_url(raw, photo)).status_code, 404)

    def test_protected_links_serve_photos_only_after_unlocking(self):
        _, raw = self.make_link(password="correct horse")
        photo = self.make_photo()
        self.assertEqual(self.client.get(self.photo_url(raw, photo)).status_code, 404)
        self.client.post(self.url(raw), {"password": "correct horse"})
        self.assertEqual(self.client.get(self.photo_url(raw, photo)).status_code, 200)