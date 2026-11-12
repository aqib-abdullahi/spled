from django.contrib.gis.geos import Point, Polygon
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import Site

BOX = Polygon(
    ((7.399, 9.069), (7.401, 9.069), (7.401, 9.071), (7.399, 9.071), (7.399, 9.069)),
    srid=4326,
)


def make_site(org, name, **kwargs):
    return Site.objects.create(
        organisation=org, name=name, kind="road",
        location=Point(7.4, 9.07, srid=4326), **kwargs,
    )


class PublicMapTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Works Dept", kind="government", verification="verified",
            public_name="Ministry of Works",
        )
        self.public = make_site(self.org, "Public Road", is_public=True, status="delayed", progress=40)

    def data(self):
        r = self.client.get(reverse("public_map_data"))
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_map_page_is_public(self):
        r = self.client.get(reverse("public_map"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "data-public-map")

    def test_map_page_lists_only_public_projects(self):
        make_site(self.org, "Private Road")
        pending = Organisation.objects.create(name="New Co", kind="private")
        make_site(pending, "Hidden Build", is_public=True)
        make_site(self.org, "Old Road", is_public=True, archived_at="2020-01-01T00:00:00Z")
        r = self.client.get(reverse("public_map"))
        self.assertContains(r, "Public Road")
        self.assertNotContains(r, "Private Road")
        self.assertNotContains(r, "Hidden Build")
        self.assertNotContains(r, "Old Road")

    def test_data_lists_only_public_projects(self):
        make_site(self.org, "Private Road")
        pending = Organisation.objects.create(name="New Co", kind="private")
        make_site(pending, "Hidden Build", is_public=True)
        make_site(self.org, "Old Road", is_public=True, archived_at="2020-01-01T00:00:00Z")
        names = [f["properties"]["name"] for f in self.data()["features"]]
        self.assertEqual(names, ["Public Road"])

    def test_data_uses_lon_lat_order(self):
        feature = self.data()["features"][0]
        self.assertEqual(self.data()["type"], "FeatureCollection")
        self.assertEqual(feature["geometry"]["type"], "Point")
        self.assertEqual(feature["geometry"]["coordinates"], [7.4, 9.07])

    def test_data_exposes_only_public_fields(self):
        props = self.data()["features"][0]["properties"]
        self.assertEqual(
            set(props),
            {"id", "name", "status", "status_label", "progress", "kind", "organisation", "url"},
        )
        self.assertEqual(props["organisation"], "Ministry of Works")
        self.assertEqual(props["status_label"], "Delayed")
        self.assertEqual(props["url"], reverse("project", args=[self.public.pk]))

    def test_data_is_briefly_cacheable(self):
        r = self.client.get(reverse("public_map_data"))
        self.assertIn("max-age=60", r["Cache-Control"])

    def test_data_is_empty_when_nothing_is_published(self):
        Site.objects.update(is_public=False)
        self.assertEqual(self.data()["features"], [])

    def test_public_nav_links_to_the_map(self):
        self.assertContains(self.client.get(reverse("home")), reverse("public_map"))

    def test_map_assets_exist(self):
        for path in ("js/spled-map.js", "vendor/maplibre-gl.js", "vendor/maplibre-gl.css"):
            self.assertIsNotNone(finders.find(path), path)

    def test_map_bootstrap_initializes_maplibre(self):
        script = finders.find("js/spled-map.js")
        self.assertIsNotNone(script)
        with open(script, encoding="utf-8") as fh:
            self.assertIn("maplibregl.Map", fh.read())


class StaffMapTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.editor = User.objects.create_user("e@example.com", "pw12345678", full_name="E")
        Membership.objects.create(user=self.editor, organisation=self.org, role="editor")
        self.site = make_site(self.org, "Riverside")

    def login(self):
        self.client.login(username="e@example.com", password="pw12345678")

    def test_site_page_has_a_map_with_coordinates(self):
        self.login()
        r = self.client.get(reverse("site_detail", args=[self.site.pk]))
        self.assertContains(r, "data-site-map")
        self.assertContains(r, 'data-lat="9.070000"')
        self.assertContains(r, 'data-lon="7.400000"')
        self.assertNotContains(r, "data-boundary")

    def test_site_page_includes_the_boundary_when_drawn(self):
        Site.objects.filter(pk=self.site.pk).update(boundary=BOX)
        self.login()
        r = self.client.get(reverse("site_detail", args=[self.site.pk]))
        self.assertContains(r, "data-boundary")
        self.assertContains(r, "Polygon")

    def test_public_project_page_has_a_map(self):
        Site.objects.filter(pk=self.site.pk).update(is_public=True)
        r = self.client.get(reverse("project", args=[self.site.pk]))
        self.assertContains(r, "data-site-map")

    def test_site_form_has_the_pin_picker(self):
        self.login()
        r = self.client.get(reverse("site_new"))
        self.assertContains(r, "data-pin-picker")
        self.assertContains(r, 'data-lat-input="id_latitude"')
        self.assertContains(r, 'id="id_latitude"')