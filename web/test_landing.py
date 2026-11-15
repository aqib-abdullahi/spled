from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class LandingPageTests(TestCase):
    def get(self):
        return self.client.get(reverse("home"))

    def test_one_h1(self):
        self.assertContains(self.get(), "<h1>", count=1)

    def test_steps_and_audiences_are_three_equal_cards(self):
        r = self.get()
        self.assertContains(r, 'aria-label="Who Spled is for"')
        self.assertContains(r, 'class="lp-card lp-step"', count=3)
        self.assertContains(r, 'class="lp-card lp-aud"', count=3)
        for text in ("Agencies and developers", "Owners watching from afar", "The public"):
            with self.subTest(text=text):
                self.assertContains(r, text)

    def test_faq_has_five_questions(self):
        r = self.get()
        self.assertContains(r, 'aria-label="Frequently asked questions"')
        self.assertContains(r, "<details>", count=5)

    def test_faq_is_honest_about_offline_capture(self):
        self.assertContains(self.get(), "Offline capture is not available yet")

    def test_evidence_section_states_its_limits_and_links_on(self):
        r = self.get()
        self.assertContains(r, 'aria-label="What verified on site means"')
        self.assertContains(r, "What it does not prove.")
        self.assertContains(r, 'href="%s"' % reverse("how_it_works"))

    def test_signed_out_calls_to_action(self):
        r = self.get()
        for name in ("signup", "signin", "projects", "public_map"):
            with self.subTest(link=name):
                self.assertContains(r, 'href="%s"' % reverse(name))
        self.assertNotContains(r, "Open workspace")
        self.assertNotContains(r, "Open dashboard")

    def test_signed_in_home_has_no_signup_links(self):
        User.objects.create_user("a@example.com", "pw12345678", full_name="A")
        self.client.login(username="a@example.com", password="pw12345678")
        r = self.get()
        self.assertNotContains(r, 'href="%s"' % reverse("signup"))
        self.assertContains(r, 'href="%s"' % reverse("overview"))

    def test_no_invented_social_proof(self):
        r = self.get()
        for text in ("Trusted by", "customers", "testimonial", "per month", "Pricing"):
            with self.subTest(text=text):
                self.assertNotContains(r, text)