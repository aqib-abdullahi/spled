from django.contrib.gis.geos import Point, Polygon
from django.db import DatabaseError,connection, transaction
from django.test import TestCase

from accounts.models import User
from organisations.models import Organisation

from .models import EvidenceEntry, Site


class EvidenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "t@example.com", "pw12345678", full_name="T"
        )
        self.org = Organisation.objects.create(name="Org", kind="government")
        lon, lat, d = 7.3986, 9.0765, 0.001
        self.site = Site.objects.create(
            organisation=self.org,
            name="Site",
            kind="power",
            location=Point(lon, lat, srid=4326),
            boundary=Polygon(
                (
                    (lon - d, lat - d),
                    (lon + d, lat - d),
                    (lon + d, lat + d),
                    (lon - d, lat + d),
                    (lon - d, lat - d),
                ),
                srid=4326,
            ),
        )

    def add(self, body="x", point=None, **kwargs):
        return EvidenceEntry.objects.create(
            site=self.site,
            author=self.user,
            kind="note",
            body=body,
            location=point,
            **kwargs,
        )

    def test_entry_inside_boundary_is_verified(self):
        e = self.add(point=Point(7.3987, 9.0766, srid=4326))
        self.assertTrue(e.verified_on_site)
        self.assertLess(e.distance_to_site_m, 50)

    def test_entry_far_away_is_not_verified(self):
        e = self.add(point=Point(7.5, 9.2, srid=4326))
        self.assertFalse(e.verified_on_site)
        self.assertGreater(e.distance_to_site_m, 1000)

    def test_entry_without_location_is_not_verified(self):
        e = self.add()
        self.assertFalse(e.verified_on_site)
        self.assertIsNone(e.distance_to_site_m)

    def test_entries_cannot_be_edited_or_deleted(self):
        e = self.add()
        e.body = "changed"
        with self.assertRaises(PermissionError):
            e.save()
        with self.assertRaises(PermissionError):
            e.delete()
        with self.assertRaises(PermissionError):
            EvidenceEntry.objects.all().delete()
        with self.assertRaises(PermissionError):
            EvidenceEntry.objects.all().update(body="changed")

    def test_chain_links_and_verifies(self):
        e1 = self.add("a")
        e2 = self.add("b")
        self.assertEqual(e1.previous_hash, "")
        self.assertEqual(e2.previous_hash, e1.content_hash)
        self.assertEqual(EvidenceEntry.verify_chain(self.site), [])

    def test_database_refuses_raw_changes(self):
        e = self.add("a")
        for sql in (
            "UPDATE registry_evidenceentry SET body = 'x'",
            "DELETE FROM registry_evidenceentry",
            "TRUNCATE registry_evidenceentry",
        ):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql)
        e.refresh_from_db()
        self.assertEqual(e.body, "a")

        def test_tampering_is_detected(self):
            e1 = self.add("a")
            self.add("b")
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(
                    "ALTER TABLE registry_evidenceentry "
                    "DISABLE TRIGGER evidence_no_update_delete"
                )
                cursor.execute(
                    "UPDATE registry_evidenceentry SET body = %s WHERE id = %s",
                    ["tampered", e1.id],
                )
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(
                    "ALTER TABLE registry_evidenceentry "
                    "ENABLE TRIGGER evidence_no_update_delete"
                )
            problems = EvidenceEntry.verify_chain(self.site)
            self.assertIn(e1.id, [p[0] for p in problems])

    def test_amendment_keeps_the_original(self):
        original = self.add("original")
        with self.assertRaises(ValueError):
            self.add("fix", amends=original)
        fix = self.add("fixed", amends=original, amendment_reason="Typo")
        self.assertEqual(fix.amends_id, original.id)
        original.refresh_from_db()
        self.assertEqual(original.body, "original")