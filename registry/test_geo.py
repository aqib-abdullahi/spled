import json
import math

from django.contrib.gis.geos import Point, Polygon
from django.test import SimpleTestCase, TestCase

from accounts.models import User
from organisations.models import Organisation

from .geo import MAX_POINTS, area_hectares, parse_boundary
from .models import EvidenceEntry, Site


def square(lon=7.4, lat=9.07, half=0.0005):
    ring = [
        [lon - half, lat - half], [lon + half, lat - half],
        [lon + half, lat + half], [lon - half, lat + half],
        [lon - half, lat - half],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def circle(n):
    ring = [
        [7.4 + 0.001 * math.cos(2 * math.pi * i / n),
         9.07 + 0.001 * math.sin(2 * math.pi * i / n)]
        for i in range(n)
    ]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


class ParseBoundaryTests(SimpleTestCase):
    def parse(self, geometry):
        return parse_boundary(json.dumps(geometry))

    def refuses(self, geometry):
        raw = geometry if isinstance(geometry, str) else json.dumps(geometry)
        with self.assertRaises(ValueError):
            parse_boundary(raw)

    def test_area_of_a_small_square(self):
        polygon = self.parse(square())
        self.assertGreater(area_hectares(polygon), 1.15)
        self.assertLess(area_hectares(polygon), 1.30)

    def test_empty_means_no_boundary(self):
        for raw in ("", "   ", None):
            self.assertIsNone(parse_boundary(raw))

    def test_a_valid_polygon_is_parsed(self):
        polygon = self.parse(square())
        self.assertEqual(polygon.srid, 4326)
        self.assertTrue(polygon.valid)
        self.assertTrue(polygon.contains(Point(7.4, 9.07, srid=4326)))

    def test_unreadable_input_is_refused(self):
        self.refuses("{not json")
        self.refuses("[1, 2, 3]")
        self.refuses('"text"')

    def test_other_geometry_types_are_refused(self):
        self.refuses({"type": "Point", "coordinates": [7.4, 9.07]})
        self.refuses({"type": "LineString", "coordinates": [[7.4, 9.07], [7.5, 9.1]]})

    def test_holes_are_refused(self):
        geometry = square()
        geometry["coordinates"].append(square(half=0.0001)["coordinates"][0])
        self.refuses(geometry)

    def test_an_unclosed_ring_is_refused(self):
        geometry = square()
        geometry["coordinates"][0].pop()
        self.refuses(geometry)

    def test_too_few_points_are_refused(self):
        self.refuses({"type": "Polygon", "coordinates": [[[7.4, 9.07], [7.401, 9.07], [7.4, 9.07]]]})
        self.refuses({"type": "Polygon", "coordinates": [[[7.4, 9.07], [7.401, 9.07], [7.4, 9.07], [7.4, 9.07]]]})

    def test_points_outside_the_world_are_refused(self):
        geometry = square()
        geometry["coordinates"][0][1] = [7.4, 95.0]
        self.refuses(geometry)
        geometry = square()
        geometry["coordinates"][0][2] = [190.0, 9.07]
        self.refuses(geometry)

    def test_non_numbers_are_refused(self):
        geometry = square()
        geometry["coordinates"][0][1] = ["a", "b"]
        self.refuses(geometry)
        geometry = square()
        geometry["coordinates"][0][1] = [True, False]
        self.refuses(geometry)
        self.refuses('{"type":"Polygon","coordinates":[[[NaN,0],[1,0],[1,1],[NaN,0]]]}')

    def test_a_shape_that_crosses_itself_is_refused(self):
        bowtie = [
            [7.400, 9.070], [7.401, 9.071], [7.401, 9.070],
            [7.400, 9.071], [7.400, 9.070],
        ]
        self.refuses({"type": "Polygon", "coordinates": [bowtie]})

    def test_a_shape_with_no_area_is_refused(self):
        line = [[7.400, 9.07], [7.401, 9.07], [7.402, 9.07], [7.400, 9.07]]
        self.refuses({"type": "Polygon", "coordinates": [line]})

    def test_the_point_limit(self):
        self.assertIsNotNone(self.parse(circle(MAX_POINTS)))
        self.refuses(circle(MAX_POINTS + 5))

    def test_an_enormous_shape_is_refused(self):
        self.refuses(square(half=5))


class BoundaryVerificationTests(TestCase):
    def setUp(self):
        org = Organisation.objects.create(name="Org", kind="government")
        self.user = User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        ring = square(half=0.004)["coordinates"][0]
        self.site = Site.objects.create(
            organisation=org, name="Big Site", kind="road",
            location=Point(7.4, 9.07, srid=4326),
            boundary=Polygon([tuple(c) for c in ring], srid=4326),
        )

    def entry(self, lon, lat):
        return EvidenceEntry.objects.create(
            site=self.site, author=self.user, kind="note", body="x",
            location=Point(lon, lat, srid=4326),
        )

    def test_boundary_extends_verification_beyond_the_pin_radius(self):
        e = self.entry(7.4025, 9.07)
        self.assertGreater(e.distance_to_site_m, 200)
        self.assertTrue(e.verified_on_site)

    def test_outside_the_boundary_and_far_from_the_pin_is_not_verified(self):
        e = self.entry(7.41, 9.07)
        self.assertFalse(e.verified_on_site)