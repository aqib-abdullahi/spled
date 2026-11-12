import json

from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from organisations.models import Membership, Organisation
from registry.models import Site


def square(lon=7.4, lat=9.07, half=0.0005):
    ring = [
        [lon - half, lat - half], [lon + half, lat - half],
        [lon + half, lat + half], [lon - half, lat + half],
        [lon - half, lat - half],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def polygon(**kwargs):
    ring = square(**kwargs)["coordinates"][0]
    return Polygon([tuple(c) for c in ring], srid=4326)


class BoundaryFormTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.editor = User.objects.create_user("editor@example.com", "pw12345678", full_name="E")
        self.viewer = User.objects.create_user("viewer@example.com", "pw12345678", full_name="V")
        Membership.objects.create(user=self.editor, organisation=self.org, role="editor")
        Membership.objects.create(user=self.viewer, organisation=self.org, role="viewer")
        self.site = Site.objects.create(
            organisation=self.org, name="Riverside", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )

    def login(self, who="editor"):
        self.client.login(username=f"{who}@example.com", password="pw12345678")

    def data(self, **extra):
        d = {
            "name": "Riverside", "kind": "road", "status": "planned",
            "owner_name": "", "target_date": "", "progress": 0,
            "latitude": 9.07, "longitude": 7.4, "description": "",
        }
        d.update(extra)
        return d

    def edit(self, who="editor", **extra):
        self.login(who)
        return self.client.post(reverse("site_edit", args=[self.site.pk]), self.data(**extra))

    def give_boundary(self):
        Site.objects.filter(pk=self.site.pk).update(boundary=polygon())
        self.site.refresh_from_db()

    def test_new_site_page_has_the_drawing_tools(self):
        self.login()
        r = self.client.get(reverse("site_new"))
        self.assertContains(r, 'data-mode="boundary"')
        self.assertContains(r, 'name="boundary"')

    def test_create_with_a_boundary(self):
        self.login()
        r = self.client.post(
            reverse("site_new"),
            self.data(name="New Road", boundary=json.dumps(square())),
        )
        self.assertRedirects(r, reverse("sites"))
        site = Site.objects.get(name="New Road")
        self.assertIsNotNone(site.boundary)
        self.assertTrue(site.boundary.contains(site.location))

    def test_create_without_a_boundary(self):
        self.login()
        self.client.post(reverse("site_new"), self.data(name="New Road"))
        self.assertIsNone(Site.objects.get(name="New Road").boundary)

    def test_edit_adds_a_boundary_and_logs_it(self):
        r = self.edit(boundary=json.dumps(square()))
        self.assertRedirects(r, reverse("sites"))
        self.site.refresh_from_db()
        self.assertIsNotNone(self.site.boundary)
        event = AuditEvent.objects.get()
        self.assertEqual(event.action, "site.edited")
        self.assertEqual(event.detail["fields"], ["Boundary"])

    def test_an_unchanged_boundary_is_not_logged(self):
        self.give_boundary()
        self.edit(boundary=self.site.boundary.geojson)
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.site.refresh_from_db()
        self.assertIsNotNone(self.site.boundary)

    def test_clearing_the_boundary(self):
        self.give_boundary()
        self.edit(boundary="")
        self.site.refresh_from_db()
        self.assertIsNone(self.site.boundary)
        self.assertEqual(AuditEvent.objects.get().detail["fields"], ["Boundary"])

    def test_a_request_without_the_field_keeps_the_boundary(self):
        self.give_boundary()
        self.edit()
        self.site.refresh_from_db()
        self.assertIsNotNone(self.site.boundary)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_a_pin_outside_the_boundary_is_refused(self):
        r = self.edit(boundary=json.dumps(square(lon=7.5, lat=9.2)))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "must be inside the boundary")
        self.site.refresh_from_db()
        self.assertIsNone(self.site.boundary)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_a_self_crossing_boundary_is_refused(self):
        bowtie = {
            "type": "Polygon",
            "coordinates": [[
                [7.3995, 9.0695], [7.4005, 9.0705], [7.4005, 9.0695],
                [7.3995, 9.0705], [7.3995, 9.0695],
            ]],
        }
        r = self.edit(boundary=json.dumps(bowtie))
        self.assertEqual(r.status_code, 200)
        self.site.refresh_from_db()
        self.assertIsNone(self.site.boundary)

    def test_an_unreadable_boundary_is_refused(self):
        r = self.edit(boundary="{oops")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "couldn’t be read")
        self.site.refresh_from_db()
        self.assertIsNone(self.site.boundary)

    def test_a_viewer_cannot_change_the_boundary(self):
        r = self.edit(who="viewer", boundary=json.dumps(square()))
        self.assertEqual(r.status_code, 403)
        self.site.refresh_from_db()
        self.assertIsNone(self.site.boundary)

    def test_the_site_page_shows_the_area(self):
        self.give_boundary()
        self.login()
        r = self.client.get(reverse("site_detail", args=[self.site.pk]))
        self.assertContains(r, "Boundary 1.2 ha")
        self.assertContains(r, "data-boundary")

    def test_the_edit_page_preloads_the_boundary(self):
        self.give_boundary()
        self.login()
        r = self.client.get(reverse("site_edit", args=[self.site.pk]))
        self.assertContains(r, 'name="boundary"')
        self.assertContains(r, 'data-boundary-input="id_boundary"')
        self.assertContains(r, "Polygon")