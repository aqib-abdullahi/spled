import re

from django.core import mail, signing
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from organisations.models import Invitation, Membership, Organisation

from .signup_views import VERIFY_SALT

GOOD = "s3cure-Passw0rd!"
OLD = "old-Passw0rd!x"
NEW = "new-S3cure-Passw0rd!"


def signup_data(**extra):
    data = {
        "full_name": "Ada Obi",
        "email": "ada@example.com",
        "organisation_name": "Works Dept",
        "kind": "government",
        "password1": GOOD,
    }
    data.update(extra)
    return data


class SignUpTests(TestCase):
    def sign_up(self, **extra):
        return self.client.post(reverse("signup"), signup_data(**extra))

    def link(self, message=None):
        body = (message or mail.outbox[-1]).body
        return re.search(r"https?://[^\s]+/signup/verify/[^\s]+", body).group(0)

    def token(self):
        return self.link().rstrip("/").rsplit("/", 1)[-1]

    def sign_in(self, password=GOOD):
        return self.client.post(
            reverse("signin"), {"username": "ada@example.com", "password": password}
        )

    def test_page_loads(self):
        self.assertEqual(self.client.get(reverse("signup")).status_code, 200)

    def test_sign_up_creates_user_organisation_membership_and_email(self):
        self.assertRedirects(self.sign_up(), reverse("signup_sent"))
        user = User.objects.get(email="ada@example.com")
        self.assertFalse(user.is_active)
        self.assertIsNone(user.email_verified_at)
        org = Organisation.objects.get()
        self.assertEqual((org.name, org.kind), ("Works Dept", "government"))
        self.assertEqual(org.verification, "pending")
        self.assertEqual(Membership.objects.get(user=user).role, "admin")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ada@example.com"])

    def test_cannot_sign_in_before_verifying(self):
        self.sign_up()
        r = self.sign_in()
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Verify your email first")

    def test_wrong_password_for_an_unverified_account_gets_the_generic_message(self):
        self.sign_up()
        r = self.sign_in("wrong")
        self.assertContains(r, "don’t match")
        self.assertNotContains(r, "Verify your email first")

    def test_verification_link_activates_the_account(self):
        self.sign_up()
        r = self.client.get(self.link())
        self.assertContains(r, "Email verified")
        user = User.objects.get(email="ada@example.com")
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.email_verified_at)
        self.assertRedirects(self.sign_in(), reverse("overview"))
        self.assertEqual(Organisation.objects.get().verification, "pending")

    def test_link_cannot_be_used_twice(self):
        self.sign_up()
        self.client.get(self.link())
        first = User.objects.get(email="ada@example.com").email_verified_at
        r = self.client.get(self.link())
        self.assertContains(r, "Already verified")
        self.assertEqual(User.objects.get(email="ada@example.com").email_verified_at, first)

    def test_tampered_link_is_refused(self):
        self.sign_up()
        token = self.token()
        bad = token[:-1] + ("a" if token[-1] != "a" else "b")
        r = self.client.get(reverse("verify_email", args=[bad]))
        self.assertContains(r, "isn’t valid")
        self.assertFalse(User.objects.get(email="ada@example.com").is_active)

    @override_settings(EMAIL_VERIFY_MAX_AGE=-1)
    def test_expired_link_is_refused(self):
        self.sign_up()
        r = self.client.get(self.link())
        self.assertContains(r, "isn’t valid")
        self.assertFalse(User.objects.get(email="ada@example.com").is_active)

    def test_link_for_a_changed_email_is_refused(self):
        self.sign_up()
        user = User.objects.get(email="ada@example.com")
        token = signing.dumps({"u": user.pk, "e": "old@example.com"}, salt=VERIFY_SALT)
        r = self.client.get(reverse("verify_email", args=[token]))
        self.assertContains(r, "isn’t valid")
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_a_deactivated_user_is_not_reactivated_by_a_link(self):
        user = User.objects.create_user(
            "x@example.com", GOOD, full_name="X",
            is_active=False, email_verified_at=timezone.now(),
        )
        token = signing.dumps({"u": user.pk, "e": user.email}, salt=VERIFY_SALT)
        r = self.client.get(reverse("verify_email", args=[token]))
        self.assertContains(r, "Already verified")
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_an_existing_email_reveals_nothing(self):
        User.objects.create_user("ada@example.com", GOOD, full_name="Ada")
        r = self.sign_up()
        self.assertRedirects(r, reverse("signup_sent"))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Organisation.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "You already have a Spled account")
        self.assertNotIn("/signup/verify/", mail.outbox[0].body)

    def test_signing_up_again_while_unverified_resends_the_link(self):
        self.sign_up()
        self.sign_up()
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Organisation.objects.count(), 1)
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("/signup/verify/", mail.outbox[1].body)

    def test_a_weak_password_is_refused(self):
        r = self.sign_up(password1="abc")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_a_missing_organisation_name_is_refused(self):
        r = self.sign_up(organisation_name="")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_an_unknown_organisation_type_is_refused(self):
        r = self.sign_up(kind="alien")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Organisation.objects.count(), 0)

    def test_a_signed_in_user_is_sent_to_the_overview(self):
        User.objects.create_user("ada@example.com", GOOD, full_name="Ada")
        self.client.login(username="ada@example.com", password=GOOD)
        self.assertRedirects(self.client.get(reverse("signup")), reverse("overview"))

    def test_resend_only_sends_to_unverified_accounts(self):
        User.objects.create_user("u@example.com", GOOD, full_name="U", is_active=False)
        User.objects.create_user(
            "v@example.com", GOOD, full_name="V", email_verified_at=timezone.now()
        )
        for email in ("u@example.com", "v@example.com", "nobody@example.com"):
            r = self.client.post(reverse("resend_verification"), {"email": email})
            self.assertRedirects(r, reverse("signup_sent"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["u@example.com"])

    def test_email_is_stored_in_lowercase(self):
        self.sign_up(email="ADA@Example.COM")
        self.assertTrue(User.objects.filter(email="ada@example.com").exists())

    def test_people_who_join_by_invitation_are_marked_verified(self):
        org = Organisation.objects.create(name="Org", kind="government")
        admin = User.objects.create_user("boss@example.com", GOOD, full_name="Boss")
        Membership.objects.create(user=admin, organisation=org, role="admin")
        _, raw = Invitation.create_for(org, "new@example.com", "viewer", admin)
        self.client.post(
            reverse("invite_accept", args=[raw]),
            {"full_name": "New Person", "password1": GOOD},
        )
        self.assertIsNotNone(User.objects.get(email="new@example.com").email_verified_at)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("p@example.com", OLD, full_name="P")

    def request_reset(self, email="p@example.com"):
        return self.client.post(reverse("password_reset"), {"email": email})

    def reset_link(self):
        return re.search(r"/reset/[^\s]+", mail.outbox[0].body).group(0)

    def test_page_loads(self):
        self.assertEqual(self.client.get(reverse("password_reset")).status_code, 200)

    def test_reset_email_is_sent_for_a_known_address(self):
        self.assertRedirects(self.request_reset(), reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Reset your Spled password")
        self.assertEqual(mail.outbox[0].to, ["p@example.com"])

    def test_an_unknown_address_sends_nothing_but_looks_the_same(self):
        self.assertRedirects(
            self.request_reset("nobody@example.com"), reverse("password_reset_done")
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_full_reset_flow(self):
        self.request_reset()
        r = self.client.get(self.reset_link(), follow=True)
        self.assertEqual(r.status_code, 200)
        set_url = r.redirect_chain[-1][0]
        r = self.client.post(set_url, {"new_password1": NEW, "new_password2": NEW})
        self.assertRedirects(r, reverse("password_reset_complete"))
        self.assertFalse(self.client.login(username="p@example.com", password=OLD))
        self.assertTrue(self.client.login(username="p@example.com", password=NEW))

    def test_a_reset_link_cannot_be_used_twice(self):
        self.request_reset()
        link = self.reset_link()
        r = self.client.get(link, follow=True)
        self.client.post(
            r.redirect_chain[-1][0], {"new_password1": NEW, "new_password2": NEW}
        )
        self.assertContains(self.client.get(link), "isn’t valid")

    def test_mismatched_passwords_are_refused(self):
        self.request_reset()
        r = self.client.get(self.reset_link(), follow=True)
        r = self.client.post(
            r.redirect_chain[-1][0],
            {"new_password1": NEW, "new_password2": NEW + "x"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.client.login(username="p@example.com", password=OLD))

    def test_a_weak_password_is_refused(self):
        self.request_reset()
        r = self.client.get(self.reset_link(), follow=True)
        r = self.client.post(
            r.redirect_chain[-1][0], {"new_password1": "abc", "new_password2": "abc"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.client.login(username="p@example.com", password=OLD))


# --- Step 57: client-side validation ---
import re  # noqa: E402
from pathlib import Path  # noqa: E402

from django.conf import settings  # noqa: E402
from django.test import TestCase  # noqa: E402
from django.urls import reverse  # noqa: E402

VALIDATE_JS = Path(settings.BASE_DIR) / "static" / "js" / "spled-validate.js"


class ClientValidationWiringTests(TestCase):
    def test_pages_load_the_validation_script_deferred(self):
        for name in ("signin", "signup", "home"):
            with self.subTest(page=name):
                r = self.client.get(reverse(name))
                self.assertContains(r, "js/spled-validate.js")
                self.assertContains(r, "spled-validate.js\" defer></script>")

    def test_password_length_in_the_script_matches_the_server_rule(self):
        server = next(
            v["OPTIONS"]["min_length"]
            for v in settings.AUTH_PASSWORD_VALIDATORS
            if v["NAME"].endswith("MinimumLengthValidator") and "OPTIONS" in v
        )
        text = VALIDATE_JS.read_text(encoding="utf-8")
        client = int(re.search(r"var MIN_PASSWORD = (\d+);", text).group(1))
        self.assertEqual(client, server)

    def test_the_script_never_sends_what_people_type_anywhere(self):
        text = VALIDATE_JS.read_text(encoding="utf-8")
        for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket",
                       "localStorage", "sessionStorage", "document.cookie"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, text)

    def test_server_rendered_fields_carry_the_attributes_the_script_relies_on(self):
        r = self.client.get(reverse("signup"))
        self.assertContains(r, 'type="email"')
        self.assertContains(r, "required")
        self.assertContains(r, "novalidate")
        self.assertContains(r, 'name="password1"')

    def test_invalid_field_styles_exist(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "spled.css").read_text(encoding="utf-8")
        self.assertIn('[aria-invalid="true"]', css)


class ClientSubmitTests(TestCase):
    def js(self):
        return VALIDATE_JS.read_text(encoding="utf-8")

    def test_messages_appear_only_when_the_button_is_pressed(self):
        text = self.js()
        for gone in ("focusout", "refreshGate", "is-gated", "form-gate-hint", "pointerdown"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, text)
        css = (Path(settings.BASE_DIR) / "static" / "css" / "spled.css").read_text(encoding="utf-8")
        self.assertNotIn("Step 58", css)

    def test_a_valid_form_shows_a_spinner_and_cannot_be_sent_twice(self):
        text = self.js()
        for needle in ("is-loading", "data-loading-note", "aria-busy", "SUBMIT_LOCK_MS", "data-allow-repeat"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
        css = (Path(settings.BASE_DIR) / "static" / "css" / "spled.css").read_text(encoding="utf-8")
        block = css[css.index("Step 59"):]
        self.assertIn("@keyframes spled-spin", block)
        self.assertIn(".is-loading::after", block)
        self.assertIn("prefers-reduced-motion", block)

    def test_the_submit_button_is_never_really_disabled(self):
        # a disabled button drops its name and value from what the browser sends
        text = self.js()
        self.assertNotIn(".disabled = true", text)
        self.assertNotIn('setAttribute("disabled"', text)

    def test_going_back_restores_the_button(self):
        text = self.js()
        self.assertIn('"pageshow"', text)
        self.assertIn("e.persisted", text)




class TypeScaleTests(TestCase):
    def block(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "spled.css").read_text(encoding="utf-8")
        return css[css.index("Step 60"):]

    def test_body_text_is_13px_and_headings_are_smaller(self):
        block = self.block()
        self.assertIn("body { font-size: 13px; }", block)
        self.assertIn(".page h1 { font-size: 28px; }", block)

    def test_inputs_are_left_alone_so_phones_do_not_zoom_in(self):
        self.assertNotIn(".field input", self.block())
        self.assertNotIn("input {", self.block())



class SpinnerTextTests(TestCase):
    def js(self):
        return VALIDATE_JS.read_text(encoding="utf-8")

    def table(self):
        text = self.js()
        start = text.index("var LOADING_TEXT = {")
        return dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', text[start:text.index("};", start)]))

    def labels(self, html):
        found = []
        for form in re.findall(r"<form[^>]*novalidate[^>]*>(.*?)</form>", html, re.S):
            for label in re.findall(r'<button[^>]*type="submit"[^>]*>(.*?)</button>', form, re.S):
                found.append(" ".join(re.sub(r"<[^>]+>", "", label).split()))
        return found

    def test_common_buttons_say_what_is_happening(self):
        table = self.table()
        self.assertTrue(table["Sign in"].startswith("Signing in"))
        self.assertTrue(table["Create account"].startswith("Creating account"))

    def test_every_button_on_the_main_forms_has_its_own_wording(self):
        from accounts.models import User
        from organisations.models import Membership, Organisation

        table = self.table()
        pages = {"signin": ["Sign in"], "signup": ["Create account"]}
        for name, expected in pages.items():
            with self.subTest(page=name):
                found = self.labels(self.client.get(reverse(name)).content.decode())
                self.assertEqual(found, expected)
                self.assertTrue(all(label in table for label in found))

        user = User.objects.create_user("spin@example.com", "pw12345678", full_name="Spin")
        org = Organisation.objects.create(name="Spin Org", kind="government", verification="verified")
        Membership.objects.create(user=user, organisation=org, role="admin")
        self.client.login(username="spin@example.com", password="pw12345678")
        app_pages = {
            "profile": ["Save details", "Change password"],
            "team": ["Send invitation"],
            "org_settings": ["Save settings"],
            "site_new": ["Save site"],
        }
        for name, expected in app_pages.items():
            with self.subTest(page=name):
                found = self.labels(self.client.get(reverse(name)).content.decode())
                self.assertEqual(found, expected)
                self.assertTrue(all(label in table for label in found))

    def test_downloads_never_show_a_spinner(self):
        text = self.js()
        self.assertIn("function looksLikeDownload", text)
        self.assertIn("looksLikeDownload(button)", text)
        self.assertIn("download", text.split("function looksLikeDownload")[1][:300].lower())

    def test_the_ring_follows_the_words_and_takes_the_text_colour(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "spled.css").read_text(encoding="utf-8")
        block = css[css.index("reworked in Step 65"):]
        block = block[:block.index("\n/* ")]
        self.assertIn(".is-loading::after", block)
        self.assertIn("border: 2px solid currentColor", block)
        self.assertNotIn("color: transparent", block)

    def test_the_button_keeps_its_width_and_comes_back_and_unknown_labels_get_a_rule(self):
        text = self.js()
        for needle in ("minWidth", "__spledHTML", "function loadingTextFor", "IRREGULAR", "data-loading-text"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)
