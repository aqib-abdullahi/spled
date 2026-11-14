from datetime import timedelta

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import Site

PW = "pw12345678"


def make_site(org, name, status="in_progress", added_days_ago=0):
    site = Site.objects.create(
        organisation=org, name=name, kind="road", status=status,
        location=Point(7.4, 9.07, srid=4326),
    )
    if added_days_ago:
        Site.objects.filter(pk=site.pk).update(
            created_at=timezone.now() - timedelta(days=added_days_ago)
        )
    return site


class OverviewAttentionTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("a@example.com", PW, full_name="A")
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        Membership.objects.create(user=user, organisation=self.org, role="editor")
        self.client.login(username="a@example.com", password=PW)

    def get(self):
        return self.client.get(reverse("overview"))

    def names(self, response):
        return [s.name for s in response.context["attention_sites"]]

    def test_stalled_then_delayed_then_quiet(self):
        make_site(self.org, "Quiet", added_days_ago=40)
        make_site(self.org, "Late", status="delayed")
        make_site(self.org, "Stuck", status="stalled")
        make_site(self.org, "Fine")
        self.assertEqual(self.names(self.get()), ["Stuck", "Late", "Quiet"])

    def test_reasons_are_spelled_out(self):
        make_site(self.org, "Stuck", status="stalled")
        make_site(self.org, "Quiet", added_days_ago=40)
        r = self.get()
        self.assertContains(r, "Stalled")
        self.assertContains(r, "No evidence yet, added 40 days ago")

    def test_longest_quiet_comes_first(self):
        make_site(self.org, "Forty", added_days_ago=40)
        make_site(self.org, "Sixty", added_days_ago=60)
        self.assertEqual(self.names(self.get()), ["Sixty", "Forty"])

    def test_list_is_capped_at_five_with_a_more_line(self):
        for n in range(7):
            make_site(self.org, "Stuck %d" % n, status="stalled")
        r = self.get()
        self.assertEqual(len(r.context["attention_sites"]), 5)
        self.assertEqual(r.context["attention_more"], 2)
        self.assertEqual(r.context["attention_count"], 7)
        self.assertContains(r, "and 2 more")

    def test_nothing_flagged_message(self):
        make_site(self.org, "Fine")
        r = self.get()
        self.assertEqual(self.names(r), [])
        self.assertContains(r, "Nothing is flagged right now")

    def test_other_organisations_are_not_listed(self):
        other = Organisation.objects.create(name="Other", kind="private")
        make_site(other, "Not Mine", status="stalled")
        self.assertEqual(self.names(self.get()), [])
        self.assertNotContains(self.get(), "Not Mine")

    def test_section_hidden_when_there_are_no_sites(self):
        self.assertNotContains(self.get(), 'aria-label="Needs attention"')

    def test_old_priority_watch_card_is_gone(self):
        make_site(self.org, "Stuck", status="stalled")
        self.assertNotContains(self.get(), "Priority watch")