from django.contrib.auth.models import AnonymousUser
from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from organisations import permissions as p
from organisations.models import Membership, Organisation

from .access import evidence_for, public_sites, sites_for
from .models import EvidenceEntry, Site

ROLES = ["admin", "editor", "field", "contractor", "owner", "viewer"]

# Written out separately from the code on purpose: changing a permission
# means changing it in both places, deliberately.
EXPECTED = {
    p.VIEW_SITES: ROLES,
    p.LOG_EVIDENCE: ["admin", "editor", "field", "contractor"],
    p.APPROVE_ENTRIES: ["admin", "editor"],
    p.EDIT_SITES: ["admin", "editor"],
    p.AMEND_ENTRY: ["admin", "editor"],
    p.SIGN_OFF: ["admin", "editor", "owner"],
    p.PUBLISH: ["admin", "editor"],
    p.CREATE_SHARE_LINKS: ["admin", "editor", "owner"],
    p.MANAGE_TEAM: ["admin"],
    p.MANAGE_ORGANISATION: ["admin"],
}


def make_site(org, name="Site", **kwargs):
    return Site.objects.create(
        organisation=org,
        name=name,
        kind="road",
        location=Point(7.4, 9.07, srid=4326),
        **kwargs,
    )


class PermissionTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(
            name="Verified Org", kind="government", verification="verified"
        )
        self.pending = Organisation.objects.create(name="Pending Org", kind="private")
        self.users = {}
        for role in ROLES:
            user = User.objects.create_user(
                f"{role}@example.com", "pw12345678", full_name=role
            )
            Membership.objects.create(user=user, organisation=self.org, role=role)
            self.users[role] = user

    def test_role_matrix(self):
        for action, allowed in EXPECTED.items():
            for role in ROLES:
                self.assertEqual(
                    p.can(self.users[role], action, self.org),
                    role in allowed,
                    f"{role} / {action}",
                )

    def test_non_member_can_do_nothing(self):
        stranger = User.objects.create_user("s@example.com", "pw12345678", full_name="S")
        for action in EXPECTED:
            self.assertFalse(p.can(stranger, action, self.org))

    def test_anonymous_and_inactive_users_can_do_nothing(self):
        for action in EXPECTED:
            self.assertFalse(p.can(AnonymousUser(), action, self.org))
        admin = self.users["admin"]
        admin.is_active = False
        admin.save()
        self.assertFalse(p.can(admin, p.VIEW_SITES, self.org))

    def test_superuser_gets_no_access_without_membership(self):
        boss = User.objects.create_superuser("b@example.com", "pw12345678", full_name="B")
        self.assertFalse(p.can(boss, p.VIEW_SITES, self.org))

    def test_role_differs_per_organisation(self):
        user = self.users["admin"]
        Membership.objects.create(user=user, organisation=self.pending, role="viewer")
        self.assertTrue(p.can(user, p.MANAGE_TEAM, self.org))
        self.assertFalse(p.can(user, p.MANAGE_TEAM, self.pending))

    def test_unknown_action_raises(self):
        with self.assertRaises(KeyError):
            p.can(self.users["admin"], "publsh", self.org)

    def test_publishing_needs_a_verified_organisation(self):
        Membership.objects.create(
            user=self.users["admin"], organisation=self.pending, role="admin"
        )
        ok = make_site(self.org)
        blocked = make_site(self.pending)
        self.assertTrue(p.can_publish(self.users["admin"], ok))
        self.assertFalse(p.can_publish(self.users["admin"], blocked))
        self.assertFalse(p.can_publish(self.users["field"], ok))

    def test_only_contractors_need_review(self):
        for role in ROLES:
            self.assertEqual(
                p.needs_review(self.users[role], self.org), role == "contractor"
            )


class AccessTests(TestCase):
    def setUp(self):
        self.org_a = Organisation.objects.create(
            name="A", kind="government", verification="verified"
        )
        self.org_b = Organisation.objects.create(
            name="B", kind="private", verification="verified"
        )
        self.user_a = User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        Membership.objects.create(user=self.user_a, organisation=self.org_a, role="editor")
        self.site_a = make_site(self.org_a, "Site A")
        self.site_b = make_site(self.org_b, "Site B")

    def test_organisations_are_kept_apart(self):
        self.assertEqual(list(sites_for(self.user_a)), [self.site_a])

    def test_archived_sites_are_hidden_unless_asked_for(self):
        self.site_a.archive()
        self.assertEqual(sites_for(self.user_a).count(), 0)
        self.assertEqual(sites_for(self.user_a, include_archived=True).count(), 1)

    def test_anonymous_sees_no_sites(self):
        self.assertEqual(sites_for(AnonymousUser()).count(), 0)

    def test_evidence_is_kept_apart(self):
        EvidenceEntry.objects.create(
            site=self.site_a, author=self.user_a, kind="note", body="mine"
        )
        other = User.objects.create_user("o@example.com", "pw12345678", full_name="O")
        Membership.objects.create(user=other, organisation=self.org_b, role="field")
        EvidenceEntry.objects.create(
            site=self.site_b, author=other, kind="note", body="theirs"
        )
        self.assertEqual(
            list(evidence_for(self.user_a).values_list("body", flat=True)), ["mine"]
        )

    def test_public_portal_rules(self):
        pending = Organisation.objects.create(name="P", kind="private")
        visible = make_site(self.org_a, "Visible", is_public=True)
        make_site(self.org_a, "Private")
        make_site(pending, "Unverified owner", is_public=True)
        make_site(self.org_b, "Archived", is_public=True, archived_at=timezone.now())
        self.assertEqual(list(public_sites()), [visible])