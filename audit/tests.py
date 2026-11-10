from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from accounts.models import User
from organisations.models import Organisation

from .log import record
from .models import AuditEvent


class AuditModelTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Org", kind="government")
        self.user = User.objects.create_user(
            "a@example.com", "pw12345678", full_name="Ada"
        )

    def event(self):
        return record(self.user, self.org, AuditEvent.Action.SITE_CREATED, 1, "Road")

    def test_record_snapshots_who_and_what(self):
        e = self.event()
        self.assertEqual(e.actor_label, "Ada (a@example.com)")
        self.assertEqual(e.target_label, "Road")
        self.assertEqual(e.organisation, self.org)

    def test_events_cannot_be_changed_or_deleted(self):
        e = self.event()
        e.target_label = "changed"
        with self.assertRaises(PermissionError):
            e.save()
        with self.assertRaises(PermissionError):
            e.delete()
        with self.assertRaises(PermissionError):
            AuditEvent.objects.all().update(target_label="x")
        with self.assertRaises(PermissionError):
            AuditEvent.objects.all().delete()

    def test_database_refuses_raw_changes(self):
        self.event()
        for sql in (
            "UPDATE audit_auditevent SET target_label = 'x'",
            "DELETE FROM audit_auditevent",
            "TRUNCATE audit_auditevent",
        ):
            with self.assertRaises(DatabaseError):
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql)