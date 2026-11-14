import json
import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from config import map_tiles

PW = "pw12345678"
JS = Path(__file__).resolve().parent.parent / "static" / "js" / "spled-map.js"
URL = "https://tiles.example.com/{z}/{x}/{y}.png"


def page_config(response):
    match = re.search(
        r'<script id="map-config" type="application/json">(.*?)</script>',
        response.content.decode(), re.S,
    )
    assert match, "map-config block not found"
    return json.loads(match.group(1))


class TileConfigPageTests(TestCase):
    def setUp(self):
        User.objects.create_user("a@example.com", PW, full_name="A")
        self.client.login(username="a@example.com", password=PW)

    def test_page_config_matches_settings(self):
        cfg = page_config(self.client.get(reverse("staff_map")))
        self.assertEqual(cfg["tile_url"], settings.MAP_TILE_URL)
        self.assertEqual(cfg["attribution"], settings.MAP_TILE_ATTRIBUTION)
        self.assertEqual(cfg["max_zoom"], settings.MAP_TILE_MAX_ZOOM)
        self.assertEqual(cfg["tile_size"], settings.MAP_TILE_SIZE)

    @override_settings(
        MAP_TILE_URL=URL, MAP_TILE_ATTRIBUTION="Credit Test", MAP_TILE_MAX_ZOOM=17,
        MAP_TILE_SIZE=512,
    )
    def test_override_reaches_the_page(self):
        cfg = page_config(self.client.get(reverse("staff_map")))
        self.assertEqual(cfg, {
            "tile_url": URL, "attribution": "Credit Test",
            "max_zoom": 17, "tile_size": 512,
        })

    @override_settings(MAP_TILE_ATTRIBUTION="x</script><b>y")
    def test_script_closing_tag_in_attribution_is_escaped(self):
        r = self.client.get(reverse("staff_map"))
        self.assertNotIn("</script><b>", r.content.decode())
        self.assertEqual(page_config(r)["attribution"], "x</script><b>y")

    def test_public_map_page_has_the_config_too(self):
        self.client.logout()
        cfg = page_config(self.client.get(reverse("public_map")))
        self.assertEqual(cfg["tile_url"], settings.MAP_TILE_URL)


class TileConfigScriptTests(TestCase):
    def test_script_builds_its_style_from_the_page_config(self):
        text = JS.read_text(encoding="utf-8")
        self.assertIn('document.getElementById("map-config")', text)
        self.assertIn("style: buildStyle()", text)
        self.assertNotIn("var STYLE", text)


class ValidateTileSettingsTests(TestCase):
    def check(self, url=URL, attribution="Credit", max_zoom=19, tile_size=256, debug=False):
        map_tiles.validate_tile_settings(url, attribution, max_zoom, tile_size, debug)

    def test_defaults_are_valid(self):
        self.check(map_tiles.DEFAULT_URL, map_tiles.DEFAULT_ATTRIBUTION)

    def test_http_is_rejected_outside_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            self.check(url="http://tiles.example.com/{z}/{x}/{y}.png")

    def test_http_is_allowed_in_debug(self):
        self.check(url="http://localhost:8080/{z}/{x}/{y}.png", debug=True)

    def test_missing_placeholder_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            self.check(url="https://tiles.example.com/{z}/{x}.png")

    def test_blank_attribution_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            self.check(attribution="   ")

    def test_bad_max_zoom_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            self.check(max_zoom=30)