from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation

PW = "pw12345678"


def urls(response):
    cards = response.context["account_cards"] + response.context["org_cards"]
    return [c["url"] for c in cards]


class SettingsHubTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a@example.com", PW, full_name="A")
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        self.membership = Membership.objects.create(
            user=self.user, organisation=self.org, role="editor"
        )
        self.client.login(username="a@example.com", password=PW)

    def set_role(self, role):
        self.membership.role = role
        self.membership.save()

    def get(self):
        return self.client.get(reverse("settings_hub"))

    def test_signed_out_is_redirected(self):
        self.client.logout()
        self.assertRedirects(self.get(), "/signin/?next=/app/settings/")

    def test_every_member_sees_profile_and_security(self):
        for role, _ in Membership.Role.choices:
            with self.subTest(role=role):
                self.set_role(role)
                r = self.get()
                self.assertEqual(r.status_code, 200)
                self.assertIn(reverse("profile"), urls(r))
                self.assertIn(reverse("account_security"), urls(r))

    def test_editor_sees_reports_but_no_admin_cards(self):
        self.set_role("editor")
        found = urls(self.get())
        self.assertIn(reverse("reports"), found)
        for name in ("org_settings", "team", "audit_log"):
            self.assertNotIn(reverse(name), found)

    def test_admin_sees_everything(self):
        self.set_role("admin")
        r = self.get()
        found = urls(r)
        for name in ("profile", "account_security", "org_settings", "team", "audit_log", "reports"):
            self.assertIn(reverse(name), found)
        self.assertContains(r, 'href="%s"' % reverse("team"))

    def test_owner_sees_reports_but_not_team(self):
        self.set_role("owner")
        found = urls(self.get())
        self.assertIn(reverse("reports"), found)
        self.assertNotIn(reverse("team"), found)
        self.assertNotIn(reverse("org_settings"), found)

    def test_viewer_and_field_do_not_see_reports(self):
        for role in ("viewer", "field"):
            with self.subTest(role=role):
                self.set_role(role)
                self.assertNotIn(reverse("reports"), urls(self.get()))

    def test_user_without_organisation_sees_account_cards_only(self):
        User.objects.create_user("b@example.com", PW, full_name="B")
        self.client.login(username="b@example.com", password=PW)
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["org_cards"], [])
        self.assertEqual(
            urls(r), [reverse("profile"), reverse("account_security")]
        )

    def test_menu_and_drawer_link_to_the_hub(self):
        self.set_role("viewer")
        r = self.client.get(reverse("overview"))
        self.assertContains(r, 'href="%s"' % reverse("settings_hub"), count=2)

    def test_admin_menu_has_one_organisation_link(self):
        self.set_role("admin")
        r = self.client.get(reverse("overview"))
        self.assertContains(r, 'href="%s"' % reverse("org_settings"), count=1)