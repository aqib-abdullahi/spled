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



from django.test import TestCase  # noqa: E402


class LocationProvenanceTests(TestCase):
    DEVICE = dict(location_source="device", location_accuracy_m=20.0)

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.contrib.gis.geos import Point
        from organisations.models import Organisation
        from registry.models import Site

        self.user = get_user_model().objects.create_user("prov@example.com", "pw12345678", full_name="P")
        org = Organisation.objects.create(name="Prov", kind="government", verification="verified")
        self.site = Site.objects.create(
            organisation=org, name="Prov Road", kind="road", location=Point(7.4, 9.07, srid=4326)
        )
        self.near = Point(7.4003, 9.07, srid=4326)  # about 33 m from the pin
        self.far = Point(7.5, 9.07, srid=4326)      # about 11 km away

    def entry(self, **extra):
        from registry.models import EvidenceEntry

        age = extra.pop("fix_age_s", None)
        entry = EvidenceEntry(site=self.site, author=self.user, kind="note", body="x", **extra)
        entry.fix_age_s = age
        entry.save()
        return entry

    def test_a_fresh_accurate_device_fix_near_the_pin_is_verified(self):
        e = self.entry(location=self.near, fix_age_s=5, **self.DEVICE)
        self.assertTrue(e.verified_on_site)
        self.assertLess(e.distance_to_site_m, 100)

    def test_a_location_with_no_recorded_source_is_never_verified(self):
        e = self.entry(location=self.near)
        self.assertFalse(e.verified_on_site)
        self.assertLess(e.distance_to_site_m, 100)

    def test_a_device_fix_far_from_the_site_is_not_verified(self):
        e = self.entry(location=self.far, fix_age_s=5, **self.DEVICE)
        self.assertFalse(e.verified_on_site)
        self.assertGreater(e.distance_to_site_m, 1000)

    def test_a_vague_fix_is_not_verified(self):
        e = self.entry(location=self.near, fix_age_s=5, location_source="device", location_accuracy_m=250.0)
        self.assertFalse(e.verified_on_site)

    def test_a_stale_fix_is_not_verified_and_a_recent_one_is(self):
        self.assertFalse(self.entry(location=self.near, fix_age_s=11 * 60, **self.DEVICE).verified_on_site)
        self.assertTrue(self.entry(location=self.near, fix_age_s=9 * 60, **self.DEVICE).verified_on_site)

    def test_a_device_fix_with_no_age_is_not_verified(self):
        self.assertFalse(self.entry(location=self.near, **self.DEVICE).verified_on_site)

    def test_a_device_fix_inside_the_boundary_is_verified_even_far_from_the_pin(self):
        from django.contrib.gis.geos import Point, Polygon

        self.site.boundary = Polygon(
            ((7.39, 9.06), (7.43, 9.06), (7.43, 9.08), (7.39, 9.08), (7.39, 9.06)), srid=4326
        )
        self.site.save()
        e = self.entry(location=Point(7.42, 9.07, srid=4326), fix_age_s=5, **self.DEVICE)
        self.assertGreater(e.distance_to_site_m, 1000)
        self.assertTrue(e.verified_on_site)

    def test_the_fix_time_is_server_time_minus_the_age_reported(self):
        e = self.entry(location=self.near, fix_age_s=120, **self.DEVICE)
        self.assertAlmostEqual((e.created_at - e.location_fixed_at).total_seconds(), 120, places=3)

    def test_provenance_is_part_of_the_fingerprint_and_survives_a_database_round_trip(self):
        from registry.models import EvidenceEntry

        e = self.entry(location=self.near, fix_age_s=30, **self.DEVICE)
        self.assertEqual(EvidenceEntry.verify_chain(self.site), [])
        e.location_accuracy_m = 5.0
        self.assertNotEqual(e.compute_hash(), e.content_hash)

    def test_entries_without_provenance_keep_their_original_fingerprint(self):
        from registry.models import EvidenceEntry

        e = self.entry(location=self.near)
        self.entry(body_extra=None) if False else None
        e.location_accuracy_m = 99.0
        self.assertEqual(e.compute_hash(), e.content_hash)
        self.assertEqual(EvidenceEntry.verify_chain(self.site), [])

    def test_the_migrations_match_the_models(self):
        from django.core.management import call_command

        call_command("makemigrations", "registry", check=True, dry_run=True, verbosity=0)
