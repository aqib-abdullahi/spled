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


class CompleteSitesAreNotQuietTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("a@example.com", PW, full_name="A")
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        Membership.objects.create(user=user, organisation=self.org, role="editor")
        self.client.login(username="a@example.com", password=PW)

    def get(self):
        return self.client.get(reverse("overview"))

    def test_old_complete_site_is_not_flagged(self):
        make_site(self.org, "Finished", status="complete", added_days_ago=90)
        r = self.get()
        self.assertEqual(r.context["attention_sites"], [])
        self.assertEqual(r.context["attention_count"], 0)

    def test_old_in_progress_site_is_still_flagged(self):
        make_site(self.org, "Quiet", status="in_progress", added_days_ago=90)
        r = self.get()
        self.assertEqual([s.name for s in r.context["attention_sites"]], ["Quiet"])
        self.assertEqual(r.context["attention_count"], 1)

    def test_old_planned_site_is_still_flagged(self):
        make_site(self.org, "Waiting", status="planned", added_days_ago=90)
        self.assertEqual(self.get().context["attention_count"], 1)

    def test_count_ignores_complete_sites_among_others(self):
        make_site(self.org, "Finished", status="complete", added_days_ago=90)
        make_site(self.org, "Stuck", status="stalled")
        make_site(self.org, "Quiet", added_days_ago=90)
        r = self.get()
        self.assertEqual(r.context["attention_count"], 2)
        self.assertEqual(
            [s.name for s in r.context["attention_sites"]], ["Stuck", "Quiet"]
        )