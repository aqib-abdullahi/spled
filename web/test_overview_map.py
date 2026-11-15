from pathlib import Path

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import Site

PW = "pw12345678"
JS = Path(__file__).resolve().parent.parent / "static" / "js" / "spled-map.js"


class OverviewMapCardTests(TestCase):
    def setUp(self):
        user = User.objects.create_user("a@example.com", PW, full_name="A")
        self.org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        Membership.objects.create(user=user, organisation=self.org, role="viewer")
        self.client.login(username="a@example.com", password=PW)

    def add_site(self, org, name):
        return Site.objects.create(
            organisation=org, name=name, kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )

    def test_card_shows_when_there_are_sites(self):
        self.add_site(self.org, "Mine One")
        r = self.client.get(reverse("overview"))
        self.assertContains(r, "data-overview-map")
        self.assertContains(r, reverse("staff_map_data"))
        self.assertContains(r, reverse("staff_map"))
        self.assertContains(r, "js/spled-map.js")

    def test_card_hidden_when_there_are_no_sites(self):
        r = self.client.get(reverse("overview"))
        self.assertNotContains(r, "data-overview-map")

    def test_other_organisations_sites_do_not_create_a_card(self):
        other = Organisation.objects.create(name="Other", kind="private")
        self.add_site(other, "Not Mine")
        r = self.client.get(reverse("overview"))
        self.assertNotContains(r, "data-overview-map")

    def test_script_starts_the_overview_map(self):
        text = JS.read_text(encoding="utf-8")
        self.assertIn("function initOverviewMap", text)
        self.assertIn('querySelectorAll("[data-overview-map]")', text)

    def test_script_still_clusters_everything(self):
        text = JS.read_text(encoding="utf-8")
        self.assertIn("cluster: true", text)
        self.assertIn('clusteredLayer(map, "sites"', text)