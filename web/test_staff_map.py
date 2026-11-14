from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import Site

PW = "pw12345678"


def make_site(org, name, status="planned", **extra):
    return Site.objects.create(
        organisation=org, name=name, kind="road", status=status,
        location=Point(7.4, 9.07, srid=4326), **extra
    )


class StaffMapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "a@example.com", PW, full_name="Secret Person Name"
        )
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.membership = Membership.objects.create(
            user=self.user, organisation=self.org, role="editor"
        )
        self.other_org = Organisation.objects.create(
            name="Other", kind="private", verification="verified"
        )
        self.client.login(username="a@example.com", password=PW)

    def names(self, response):
        return [f["properties"]["name"] for f in response.json()["features"]]

    # ---- access ----
    def test_page_needs_sign_in(self):
        self.client.logout()
        r = self.client.get(reverse("staff_map"))
        self.assertRedirects(r, "/signin/?next=/app/map/")

    def test_data_signed_out_gets_401(self):
        make_site(self.org, "Mine One")
        self.client.logout()
        r = self.client.get(reverse("staff_map_data"))
        self.assertEqual(r.status_code, 401)
        self.assertNotContains(r, "Mine One", status_code=401)

    def test_every_role_can_view_page_and_data(self):
        make_site(self.org, "Mine One")
        for role, _ in Membership.Role.choices:
            with self.subTest(role=role):
                self.membership.role = role
                self.membership.save()
                self.assertEqual(self.client.get(reverse("staff_map")).status_code, 200)
                r = self.client.get(reverse("staff_map_data"))
                self.assertEqual(r.status_code, 200)
                self.assertEqual(self.names(r), ["Mine One"])

    # ---- scoping ----
    def test_data_only_has_own_organisation_sites(self):
        make_site(self.org, "Mine One")
        make_site(self.other_org, "Not Mine")
        r = self.client.get(reverse("staff_map_data"))
        self.assertEqual(self.names(r), ["Mine One"])
        self.assertNotContains(r, "Not Mine")

    def test_data_excludes_archived_sites(self):
        make_site(self.org, "Live")
        make_site(self.org, "Gone").archive()
        self.assertEqual(self.names(self.client.get(reverse("staff_map_data"))), ["Live"])

    def test_data_includes_unpublished_sites(self):
        make_site(self.org, "Private One", is_public=False)
        make_site(self.org, "Public One", is_public=True)
        r = self.client.get(reverse("staff_map_data"))
        flags = {f["properties"]["name"]: f["properties"]["is_public"]
                 for f in r.json()["features"]}
        self.assertEqual(flags, {"Private One": False, "Public One": True})

    def test_user_without_organisation_gets_empty_collection(self):
        User.objects.create_user("b@example.com", PW, full_name="B")
        self.client.login(username="b@example.com", password=PW)
        make_site(self.org, "Mine One")
        r = self.client.get(reverse("staff_map_data"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["features"], [])

    def test_session_organisation_choice_is_respected(self):
        zeta = Organisation.objects.create(
            name="Zeta", kind="private", verification="verified"
        )
        Membership.objects.create(user=self.user, organisation=zeta, role="editor")
        make_site(self.org, "In Mine")
        make_site(zeta, "In Zeta")
        self.assertEqual(self.names(self.client.get(reverse("staff_map_data"))), ["In Mine"])
        session = self.client.session
        session["org_id"] = zeta.pk
        session.save()
        self.assertEqual(self.names(self.client.get(reverse("staff_map_data"))), ["In Zeta"])

    # ---- payload ----
    def test_payload_fields_are_exactly_these(self):
        site = make_site(self.org, "Mine One", "in_progress", progress=40)
        r = self.client.get(reverse("staff_map_data"))
        feature = r.json()["features"][0]
        self.assertEqual(feature["geometry"], {"type": "Point", "coordinates": [7.4, 9.07]})
        self.assertEqual(feature["properties"], {
            "id": site.pk,
            "name": "Mine One",
            "status": "in_progress",
            "status_label": "In progress",
            "progress": 40,
            "kind": "Road",
            "is_public": False,
            "url": reverse("site_detail", args=[site.pk]),
        })

    def test_payload_leaks_no_staff_or_description_details(self):
        make_site(
            self.org, "Mine One",
            owner_name="Hidden Owner", description="Hidden description text",
        )
        r = self.client.get(reverse("staff_map_data"))
        for secret in ("Hidden Owner", "Hidden description text",
                       "Secret Person Name", "a@example.com"):
            self.assertNotContains(r, secret)

    def test_data_is_never_cached_by_shared_caches(self):
        r = self.client.get(reverse("staff_map_data"))
        self.assertIn("no-store", r["Cache-Control"])
        self.assertIn("private", r["Cache-Control"])

    def test_data_is_capped_at_the_limit(self):
        for n in range(3):
            make_site(self.org, "Site %d" % n)
        with mock.patch("web.staff_map_views.MAP_LIMIT", 2):
            r = self.client.get(reverse("staff_map_data"))
            page = self.client.get(reverse("staff_map"))
        self.assertEqual(len(r.json()["features"]), 2)
        self.assertTrue(page.context["truncated"])

    # ---- page ----
    def test_page_lists_own_sites_only(self):
        make_site(self.org, "Mine One")
        make_site(self.other_org, "Zed Hidden Site")
        r = self.client.get(reverse("staff_map"))
        self.assertContains(r, "Mine One")
        self.assertNotContains(r, "Zed Hidden Site")

    def test_page_status_counts(self):
        make_site(self.org, "A", "in_progress")
        make_site(self.org, "B", "in_progress")
        make_site(self.org, "C", "stalled")
        make_site(self.other_org, "D", "stalled")
        counts = {s["key"]: s["count"]
                  for s in self.client.get(reverse("staff_map")).context["status_counts"]}
        self.assertEqual(counts["in_progress"], 2)
        self.assertEqual(counts["stalled"], 1)
        self.assertEqual(counts["complete"], 0)

    def test_page_without_organisation_still_loads(self):
        User.objects.create_user("b@example.com", PW, full_name="B")
        self.client.login(username="b@example.com", password=PW)
        r = self.client.get(reverse("staff_map"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "not a member of an organisation")

    # ---- the public map must not change ----
    def test_public_map_still_hides_unpublished_staff_sites(self):
        make_site(self.org, "Private One", is_public=False)
        make_site(self.org, "Public One", is_public=True)
        self.client.logout()
        r = self.client.get(reverse("public_map_data"))
        names = [f["properties"]["name"] for f in r.json()["features"]]
        self.assertEqual(names, ["Public One"])