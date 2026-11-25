from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, Site


class SignInTests(TestCase):
    def setUp(self):
        User.objects.create_user("a@example.com", "pw12345678", full_name="A")

    def test_sign_in_page_loads(self):
        self.assertEqual(self.client.get(reverse("signin")).status_code, 200)

    def test_good_credentials_reach_the_overview(self):
        r = self.client.post(
            reverse("signin"), {"username": "a@example.com", "password": "pw12345678"}
        )
        self.assertRedirects(r, reverse("overview"))

    def test_email_capitals_do_not_matter(self):
        r = self.client.post(
            reverse("signin"), {"username": "A@EXAMPLE.com", "password": "pw12345678"}
        )
        self.assertRedirects(r, reverse("overview"))

    def test_wrong_password_shows_an_error(self):
        r = self.client.post(
            reverse("signin"), {"username": "a@example.com", "password": "nope"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "don’t match")

    def test_overview_needs_sign_in(self):
        r = self.client.get(reverse("overview"))
        self.assertRedirects(r, "/signin/?next=/app/")

    def test_sign_out(self):
        self.client.login(username="a@example.com", password="pw12345678")
        r = self.client.post(reverse("signout"))
        self.assertRedirects(r, reverse("signin"))
        self.assertEqual(self.client.get(reverse("overview")).status_code, 302)


def make_site(org, name, status="planned"):
    return Site.objects.create(
        organisation=org, name=name, kind="road", status=status,
        location=Point(7.4, 9.07, srid=4326),
    )


class OverviewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        Membership.objects.create(user=self.user, organisation=self.org, role="editor")
        self.client.login(username="a@example.com", password="pw12345678")

    def test_user_without_organisation_sees_welcome(self):
        other = User.objects.create_user("b@example.com", "pw12345678", full_name="B")
        self.client.login(username="b@example.com", password="pw12345678")
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "not part of an organisation")

    def test_only_own_organisation_sites_are_shown(self):
        make_site(self.org, "Mine One")
        stranger_org = Organisation.objects.create(name="Other", kind="private")
        make_site(stranger_org, "Not Mine")
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "Mine One")
        self.assertNotContains(r, "Not Mine")

    def test_status_counts(self):
        make_site(self.org, "A", "in_progress")
        make_site(self.org, "B", "in_progress")
        make_site(self.org, "C", "complete")
        counts = {
            s["key"]: s["count"]
            for s in self.client.get(reverse("overview")).context["status_counts"]
        }
        self.assertEqual(counts["in_progress"], 2)
        self.assertEqual(counts["complete"], 1)
        self.assertEqual(counts["planned"], 0)

    def test_delayed_and_stalled_need_attention(self):
        make_site(self.org, "Fine", "in_progress")
        make_site(self.org, "Late", "delayed")
        make_site(self.org, "Stuck", "stalled")
        r = self.client.get(reverse("overview"))
        self.assertEqual(r.context["attention_count"], 2)

    def test_unverified_organisation_sees_the_notice(self):
        self.org.verification = "pending"
        self.org.save()
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "Pending verification")
        
class SitesPageTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.editor = User.objects.create_user("e@example.com", "pw12345678", full_name="E")
        self.viewer = User.objects.create_user("v@example.com", "pw12345678", full_name="V")
        Membership.objects.create(user=self.editor, organisation=self.org, role="editor")
        Membership.objects.create(user=self.viewer, organisation=self.org, role="viewer")

    def login(self, who):
        self.client.login(username=f"{who}@example.com", password="pw12345678")

    def good_data(self, **extra):
        data = {
            "name": "New Road", "kind": "road", "status": "planned",
            "owner_name": "Works", "target_date": "", "progress": 10,
            "latitude": 9.07, "longitude": 7.4, "description": "",
        }
        data.update(extra)
        return data

    def test_list_needs_sign_in(self):
        self.assertEqual(self.client.get(reverse("sites")).status_code, 302)

    def test_list_shows_only_own_organisation_sites(self):
        make_site(self.org, "Mine One")
        make_site(Organisation.objects.create(name="Other", kind="private"), "Not Mine")
        self.login("e")
        r = self.client.get(reverse("sites"))
        self.assertContains(r, "Mine One")
        self.assertNotContains(r, "Not Mine")

    def test_status_filter_and_search(self):
        make_site(self.org, "Alpha Road", "delayed")
        make_site(self.org, "Beta Bridge", "planned")
        self.login("e")
        r = self.client.get(reverse("sites"), {"status": "delayed"})
        self.assertContains(r, "Alpha Road")
        self.assertNotContains(r, "Beta Bridge")
        r = self.client.get(reverse("sites"), {"q": "bridge"})
        self.assertContains(r, "Beta Bridge")
        self.assertNotContains(r, "Alpha Road")

    def test_editor_can_create_a_site(self):
        self.login("e")
        r = self.client.post(reverse("site_new"), self.good_data())
        self.assertRedirects(r, reverse("sites"))
        site = Site.objects.get(name="New Road")
        self.assertEqual(site.organisation, self.org)
        self.assertEqual((site.location.x, site.location.y), (7.4, 9.07))

    def test_viewer_cannot_create_a_site(self):
        self.login("v")
        self.assertEqual(self.client.get(reverse("site_new")).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("site_new"), self.good_data()).status_code, 403
        )
        self.assertFalse(Site.objects.filter(name="New Road").exists())

    def test_invalid_coordinates_are_rejected(self):
        self.login("e")
        r = self.client.post(reverse("site_new"), self.good_data(latitude=123))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Site.objects.filter(name="New Road").exists())

    def test_progress_over_100_is_rejected(self):
        self.login("e")
        r = self.client.post(reverse("site_new"), self.good_data(progress=150))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Site.objects.filter(name="New Road").exists())

    def test_edit_updates_the_site_and_its_location(self):
        site = make_site(self.org, "Old Name")
        self.login("e")
        r = self.client.post(
            reverse("site_edit", args=[site.pk]),
            self.good_data(name="New Name", latitude=10.5, longitude=8.5),
        )
        self.assertRedirects(r, reverse("sites"))
        site.refresh_from_db()
        self.assertEqual(site.name, "New Name")
        self.assertEqual((site.location.x, site.location.y), (8.5, 10.5))

    def test_cannot_edit_another_organisations_site(self):
        theirs = make_site(Organisation.objects.create(name="Other", kind="private"), "Theirs")
        self.login("e")
        r = self.client.post(reverse("site_edit", args=[theirs.pk]), self.good_data())
        self.assertEqual(r.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.name, "Theirs")

class SiteDetailTests(TestCase):
    NEAR = {"latitude": 9.0701, "longitude": 7.4001}
    FAR = {"latitude": 9.5, "longitude": 7.9}

    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.users = {}
        for role in ("editor", "field", "viewer", "contractor"):
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=role.title()
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user
        self.site = make_site(self.org, "Riverside")

    def login(self, role):
        self.client.login(username=f"{role}@example.com", password="pw12345678")

    def data(self, **extra):
        d = {
            "kind": "note", "body": "Panels installed.", "tags": "",
            "latitude": "", "longitude": "", "new_status": "",
        }
        d.update(extra)
        return d

    def detail(self):
        return reverse("site_detail", args=[self.site.pk])

    def new(self):
        return reverse("evidence_new", args=[self.site.pk])

    def publish(self):
        return reverse("site_publish", args=[self.site.pk])

    def test_detail_needs_sign_in(self):
        self.assertEqual(self.client.get(self.detail()).status_code, 302)

    def test_detail_shows_site_and_evidence(self):
        EvidenceEntry.objects.create(
            site=self.site, author=self.users["editor"], kind="note",
            body="Poured foundations", location=Point(7.4001, 9.0701, srid=4326),
        )
        self.login("editor")
        r = self.client.get(self.detail())
        self.assertContains(r, "Riverside")
        self.assertContains(r, "Poured foundations")
        self.assertContains(r, "Verified on site")

    def test_cannot_view_another_organisations_site(self):
        theirs = make_site(Organisation.objects.create(name="Other", kind="private"), "Theirs")
        self.login("editor")
        r = self.client.get(reverse("site_detail", args=[theirs.pk]))
        self.assertEqual(r.status_code, 404)

    def test_viewer_sees_no_action_buttons(self):
        self.login("viewer")
        r = self.client.get(self.detail())
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Edit site")
        self.assertNotContains(r, "Log evidence")

    def test_viewer_cannot_log_evidence(self):
        self.login("viewer")
        self.assertEqual(self.client.get(self.new()).status_code, 403)
        self.assertEqual(self.client.post(self.new(), self.data()).status_code, 403)
        self.assertEqual(EvidenceEntry.objects.count(), 0)

    def test_field_can_log_a_note_and_it_is_verified(self):
        self.login("field")
        r = self.client.post(self.new(), self.data(**self.NEAR))
        self.assertRedirects(r, self.detail())
        entry = EvidenceEntry.objects.get()
        self.assertEqual(entry.author, self.users["field"])
        self.assertTrue(entry.verified_on_site)
        self.assertLess(entry.distance_to_site_m, 100)

    def test_entry_far_from_site_is_saved_but_not_verified(self):
        self.login("field")
        self.client.post(self.new(), self.data(**self.FAR))
        entry = EvidenceEntry.objects.get()
        self.assertFalse(entry.verified_on_site)

    def test_check_in_needs_a_location(self):
        self.login("field")
        r = self.client.post(self.new(), self.data(kind="check_in"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 0)

    def test_status_change_on_site_updates_the_site(self):
        self.login("editor")
        r = self.client.post(self.new(), self.data(new_status="in_progress", **self.NEAR))
        self.assertRedirects(r, self.detail())
        self.site.refresh_from_db()
        self.assertEqual(self.site.status, "in_progress")
        self.assertEqual(EvidenceEntry.objects.get().kind, "status")

    def test_status_change_far_away_is_refused_and_leaves_no_entry(self):
        self.login("editor")
        r = self.client.post(self.new(), self.data(new_status="delayed", **self.FAR))
        self.assertEqual(r.status_code, 200)
        self.site.refresh_from_db()
        self.assertEqual(self.site.status, "planned")
        self.assertEqual(EvidenceEntry.objects.count(), 0)


    def test_editor_can_publish_when_verified(self):
        self.login("editor")
        r = self.client.post(self.publish())
        self.assertRedirects(r, self.detail())
        self.site.refresh_from_db()
        self.assertTrue(self.site.is_public)

    def test_publish_is_blocked_when_the_organisation_is_unverified(self):
        self.org.verification = "pending"
        self.org.save()
        self.login("editor")
        self.client.post(self.publish())
        self.site.refresh_from_db()
        self.assertFalse(self.site.is_public)

    def test_field_role_cannot_publish(self):
        self.login("field")
        self.assertEqual(self.client.post(self.publish()).status_code, 403)
        self.site.refresh_from_db()
        self.assertFalse(self.site.is_public)

    def test_publish_needs_a_post(self):
        self.login("editor")
        self.assertEqual(self.client.get(self.publish()).status_code, 405)

    def test_unpublish(self):
        Site.objects.filter(pk=self.site.pk).update(is_public=True)
        self.login("editor")
        self.client.post(self.publish())
        self.site.refresh_from_db()
        self.assertFalse(self.site.is_public)

    def test_tags_are_cleaned(self):
        self.login("editor")
        self.client.post(self.new(), self.data(tags=" Inspection , delivery,inspection"))
        self.assertEqual(EvidenceEntry.objects.get().tags, ["inspection", "delivery"])



import re  # noqa: E402


class TypedLocationTests(TestCase):
    NEAR = {"latitude": "9.07", "longitude": "7.4003"}   # about 33 m from the pin
    FAR = {"latitude": "9.07", "longitude": "7.5"}       # about 11 km away
    FIX = {"accuracy": "12", "fix_age": "3"}

    def setUp(self):
        self.user = User.objects.create_user("typed@example.com", "pw12345678", full_name="T")
        self.org = Organisation.objects.create(name="Typed", kind="government", verification="verified")
        Membership.objects.create(user=self.user, organisation=self.org, role="editor")
        self.site = Site.objects.create(
            organisation=self.org, name="Typed Road", kind="road", location=Point(7.4, 9.07, srid=4326)
        )
        self.client.login(username="typed@example.com", password="pw12345678")
        self.url = reverse("evidence_new", args=[self.site.pk])

    def post(self, **extra):
        data = {"kind": "note", "body": "Checked the culvert"}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_the_form_has_no_box_to_type_coordinates_into(self):
        from registry.models import MAX_FIX_ACCURACY_M

        html = self.client.get(self.url).content.decode()
        for name in ("latitude", "longitude", "accuracy", "fix_age"):
            with self.subTest(field=name):
                tag = re.search(r'<input[^>]*name="%s"[^>]*>' % name, html).group(0)
                self.assertIn('type="hidden"', tag)
        self.assertIn("Use my current location", html)
        self.assertIn("var MAX_ACCURACY = %d;" % MAX_FIX_ACCURACY_M, html)

    def test_a_device_fix_near_the_pin_is_verified_and_remembered(self):
        r = self.post(**self.NEAR, **self.FIX)
        self.assertEqual(r.status_code, 302)
        e = EvidenceEntry.objects.get()
        self.assertTrue(e.verified_on_site)
        self.assertEqual((e.location_source, e.location_accuracy_m), ("device", 12.0))

    def test_coordinates_without_a_device_fix_are_refused(self):
        r = self.post(**self.NEAR)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "can’t be typed in")
        self.assertEqual(EvidenceEntry.objects.count(), 0)

    def test_a_device_fix_far_from_the_site_is_saved_but_not_verified(self):
        self.assertEqual(self.post(**self.FAR, **self.FIX).status_code, 302)
        self.assertFalse(EvidenceEntry.objects.get().verified_on_site)

    def test_a_vague_fix_is_not_verified_even_next_to_the_pin(self):
        self.assertEqual(self.post(**self.NEAR, accuracy="500", fix_age="3").status_code, 302)
        self.assertFalse(EvidenceEntry.objects.get().verified_on_site)

    def test_an_old_fix_is_not_verified(self):
        self.assertEqual(self.post(**self.NEAR, accuracy="12", fix_age="3600").status_code, 302)
        self.assertFalse(EvidenceEntry.objects.get().verified_on_site)

    def test_a_status_change_needs_a_real_nearby_device_fix(self):
        for extra in (self.NEAR, {**self.FAR, **self.FIX}):
            r = self.post(new_status="in_progress", **extra)
            self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 0)
        self.site.refresh_from_db()
        self.assertEqual(self.site.status, "planned")
        self.assertEqual(self.post(new_status="in_progress", **self.NEAR, **self.FIX).status_code, 302)
        self.site.refresh_from_db()
        self.assertEqual(self.site.status, "in_progress")

    def test_an_entry_without_a_location_still_saves_and_is_not_verified(self):
        self.assertEqual(self.post().status_code, 302)
        e = EvidenceEntry.objects.get()
        self.assertFalse(e.verified_on_site)
        self.assertEqual(e.location_source, "")

    def test_a_field_check_in_needs_a_location(self):
        r = self.post(kind="check_in")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EvidenceEntry.objects.count(), 0)

    def test_the_site_page_says_where_each_location_came_from(self):
        self.post(**self.NEAR, **self.FIX)
        old = EvidenceEntry(
            site=self.site, author=self.user, kind="note", body="Older entry",
            location=Point(7.4003, 9.07, srid=4326),
        )
        old.save()
        page = self.client.get(reverse("site_detail", args=[self.site.pk]))
        self.assertContains(page, "device location, accurate to ±12 m")
        self.assertContains(page, "location source not recorded")

    def test_the_explanation_page_states_the_device_only_rule(self):
        self.client.logout()
        page = self.client.get(reverse("how_it_works"))
        self.assertContains(page, "100 metres")
        self.assertContains(page, "can never verify an entry")
