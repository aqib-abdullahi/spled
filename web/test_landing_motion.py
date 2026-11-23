from pathlib import Path

from django.test import TestCase
from django.urls import reverse

CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "spled.css"


class LandingMotionTests(TestCase):
    def css(self):
        text = CSS.read_text(encoding="utf-8")
        return text[text.index("Step 47c"):]

    def test_faq_script_is_on_the_page_and_respects_reduced_motion(self):
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("lp-faq-anim", html)
        self.assertIn(".lp-faq details", html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn(".animate(", html)

    def test_faq_still_works_as_plain_details_without_the_script(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, "<details>", count=5)
        self.assertContains(r, "<summary>", count=5)

    def test_lifts_only_apply_on_devices_that_can_hover(self):
        css = self.css()
        self.assertIn("@media (hover: hover) and (pointer: fine)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def test_landing_links_are_underlined_and_audience_cards_are_clickable(self):
        css = self.css()
        self.assertIn("Step 56", css)
        self.assertIn(".lp-aud .lp-link::before", css)
    
    def test_cards_bulge_and_cast_a_shadow_on_hover(self):
        css = self.css()
        self.assertIn("Step 47d", css)
        self.assertIn("scale(1.025)", css)
        self.assertIn("0 24px 48px", css)


class LinkStyleTests(TestCase):
    def test_links_have_no_arrows_or_underlines_after_step_56(self):
        text = CSS.read_text(encoding="utf-8")
        block = text[text.index("Step 56"):]
        self.assertIn("content: none", block)
        self.assertNotIn('content: "\u2192"', block)
        self.assertIn("text-decoration: none", block)
        self.assertNotIn("text-decoration: underline", block)
