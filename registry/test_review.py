from django.contrib.gis.geos import Point
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import TestCase

from accounts.models import User
from organisations.models import Organisation

from .models import EvidenceEntry, EvidenceReview, Site


class ReviewModelTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Org", kind="government", verification="verified"
        )
        self.contractor = User.objects.create_user("c@example.com", "pw12345678", full_name="C")
        self.editor = User.objects.create_user("e@example.com", "pw12345678", full_name="E")
        self.site = Site.objects.create(
            organisation=self.org, name="S", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )

    def entry(self, needs_review=True, author=None, body="x"):
        return EvidenceEntry.objects.create(
            site=self.site, author=author or self.contractor, kind="note",
            body=body, needs_review=needs_review,
        )

    def review(self, entry, decision="approved", comment="", reviewer=None):
        return EvidenceReview.objects.create(
            entry=entry, reviewer=reviewer or self.editor,
            decision=decision, comment=comment,
        )

    def test_review_flag_is_part_of_the_chain(self):
        self.entry(needs_review=False)
        flagged = self.entry(needs_review=True)
        self.assertEqual(EvidenceEntry.verify_chain(self.site), [])
        flagged.needs_review = False
        self.assertNotEqual(flagged.compute_hash(), flagged.content_hash)

    def test_counted_excludes_pending_and_rejected(self):
        self.entry(needs_review=False, body="plain")
        self.entry(body="pending")
        self.review(self.entry(body="approved"))
        self.review(self.entry(body="rejected"), "rejected", "Not enough detail")
        bodies = set(
            EvidenceEntry.objects.counted().values_list("body", flat=True)
        )
        self.assertEqual(bodies, {"plain", "approved"})

    def test_review_cannot_be_changed_or_deleted(self):
        r = self.review(self.entry())
        r.comment = "changed"
        with self.assertRaises(PermissionError):
            r.save()
        with self.assertRaises(PermissionError):
            r.delete()

    def test_database_refuses_raw_review_changes(self):
        self.review(self.entry())
        for sql in (
            "UPDATE registry_evidencereview SET comment = 'x'",
            "DELETE FROM registry_evidencereview",
            "TRUNCATE registry_evidencereview",
        ):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql)

    def test_reviewer_cannot_be_the_author(self):
        mine = self.entry(author=self.editor)
        with self.assertRaises(ValueError):
            self.review(mine, reviewer=self.editor)

    def test_review_needs_a_flagged_entry(self):
        with self.assertRaises(ValueError):
            self.review(self.entry(needs_review=False))

    def test_rejection_needs_a_comment(self):
        e = self.entry()
        with self.assertRaises(ValueError):
            self.review(e, "rejected", "")
        self.assertEqual(self.review(e, "rejected", "Unclear photo").decision, "rejected")

    def test_one_review_per_entry(self):
        e = self.entry()
        self.review(e)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.review(e, "rejected", "Changed my mind")