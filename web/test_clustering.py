from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from organisations.models import Membership, Organisation

PW = "pw12345678"
JS = Path(__file__).resolve().parent.parent / "static" / "js" / "spled-map.js"


class ClusteringWiringTests(TestCase):
    def test_script_clusters_both_maps(self):
        text = JS.read_text(encoding="utf-8")
        self.assertIn("cluster: true", text)
        self.assertIn("getClusterExpansionZoom", text)
        self.assertIn('clusteredLayer(map, "projects"', text)
        self.assertIn('clusteredLayer(map, "sites"', text)

    def test_script_has_no_commented_out_copy_at_the_top(self):
        first = next(l for l in JS.read_text(encoding="utf-8").splitlines() if l.strip())
        self.assertEqual(first, "(function () {")

    def test_public_map_page_loads_the_script(self):
        r = self.client.get(reverse("public_map"))
        self.assertContains(r, "data-public-map")
        self.assertContains(r, "js/spled-map.js")

    def test_staff_map_page_loads_the_script(self):
        user = User.objects.create_user("a@example.com", PW, full_name="A")
        org = Organisation.objects.create(
            name="Mine", kind="government", verification="verified"
        )
        Membership.objects.create(user=user, organisation=org, role="editor")
        self.client.login(username="a@example.com", password=PW)
        r = self.client.get(reverse("staff_map"))
        self.assertContains(r, "data-staff-map")
        self.assertContains(r, "js/spled-map.js")