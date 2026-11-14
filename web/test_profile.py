import datetime
from unittest import mock

from django.contrib.gis.geos import Point
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_timezone

from accounts.models import User
from organisations.models import Membership, Organisation
from registry.models import EvidenceEntry, Site
from security.models import Attempt

GOOD = "s3cure-Passw0rd!"
NEW = "new-S3cure-Passw0rd!"


class ProfileDetailsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "a@example.com", GOOD, full_name="Ada Obi", phone="0800 000 0000"
        )
        self.client.login(username="a@example.com", password=GOOD)

    def save(self, **extra):
        data = {"full_name": "Ada Obi", "phone": "", "time_zone": "Africa/Lagos"}
        data.update(extra)
        return self.client.post(reverse("profile_save"), data)

    def refresh(self):
        self.user.refresh_from_db()
        return self.user

    def test_page_needs_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("profile")).status_code, 302)

    def test_page_shows_current_values(self):
        r = self.client.get(reverse("profile"))
        self.assertContains(r, "Ada Obi")
        self.assertContains(r, "a@example.com")
        self.assertContains(r, "0800 000 0000")
        self.assertContains(r, 'value="Africa/Lagos" selected')

    def test_saving_updates_the_details(self):
        r = self.save(full_name="Ada B. Obi", phone="+234 800 111 2222", time_zone="Asia/Tokyo")
        self.assertRedirects(r, reverse("profile"))
        user = self.refresh()
        self.assertEqual(user.full_name, "Ada B. Obi")
        self.assertEqual(user.phone, "+234 800 111 2222")
        self.assertEqual(user.time_zone, "Asia/Tokyo")

    def test_name_is_required(self):
        r = self.save(full_name="   ")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.refresh().full_name, "Ada Obi")

    def test_whitespace_is_tidied(self):
        self.save(full_name="  Ada    Obi  ", phone="  0800   111  ")
        user = self.refresh()
        self.assertEqual(user.full_name, "Ada Obi")
        self.assertEqual(user.phone, "0800 111")

    def test_an_unknown_time_zone_is_refused(self):
        r = self.save(time_zone="Mars/Olympus")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.refresh().time_zone, "Africa/Lagos")

    def test_a_bad_phone_number_is_refused(self):
        r = self.save(phone="call me maybe")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.refresh().phone, "0800 000 0000")

    def test_the_email_cannot_be_changed_here(self):
        self.save(email="someone-else@example.com")
        self.assertEqual(self.refresh().email, "a@example.com")

    def test_saving_only_accepts_post(self):
        self.assertEqual(self.client.get(reverse("profile_save")).status_code, 405)

    def test_the_account_menu_links_to_the_profile(self):
        self.assertContains(self.client.get(reverse("overview")), reverse("profile"))


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a@example.com", GOOD, full_name="Ada")
        self.client.login(username="a@example.com", password=GOOD)
        self.url = reverse("profile_password")

    def change(self, **extra):
        data = {"old_password": GOOD, "new_password1": NEW, "new_password2": NEW}
        data.update(extra)
        return self.client.post(self.url, data)

    def unchanged(self):
        self.user.refresh_from_db()
        return self.user.check_password(GOOD)

    def test_changing_the_password_works_and_keeps_you_signed_in(self):
        r = self.change()
        self.assertRedirects(r, reverse("profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))
        self.assertFalse(self.user.check_password(GOOD))
        self.assertEqual(self.client.get(reverse("profile")).status_code, 200)
        self.assertEqual(mail.outbox[-1].subject, "Your Spled password was changed")
        self.assertEqual(mail.outbox[-1].to, ["a@example.com"])

    def test_a_wrong_current_password_is_refused_and_counted(self):
        r = self.change(old_password="not-it")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.unchanged())
        self.assertEqual(Attempt.objects.filter(scope="password_user").count(), 1)

    def test_a_mismatched_confirmation_is_refused(self):
        r = self.change(new_password2=NEW + "x")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.unchanged())

    def test_a_short_password_is_refused(self):
        r = self.change(new_password1="Short1!x", new_password2="Short1!x")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.unchanged())

    def test_the_same_password_is_refused(self):
        r = self.change(new_password1=GOOD, new_password2=GOOD)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "different password")
        self.assertTrue(self.unchanged())

    def test_other_devices_are_signed_out(self):
        other = self.client_class()
        other.login(username="a@example.com", password=GOOD)
        self.assertEqual(other.get(reverse("overview")).status_code, 200)
        self.change()
        self.assertEqual(other.get(reverse("overview")).status_code, 302)
        self.assertEqual(self.client.get(reverse("overview")).status_code, 200)

    def test_repeated_wrong_passwords_lock_it_even_for_the_right_one(self):
        for _ in range(5):
            self.assertEqual(self.change(old_password="not-it").status_code, 200)
        r = self.change()
        self.assertEqual(r.status_code, 429)
        self.assertContains(r, "Too many attempts", status_code=429)
        self.assertTrue(self.unchanged())

    def test_the_lock_does_not_affect_other_accounts(self):
        for _ in range(5):
            self.change(old_password="not-it")
        User.objects.create_user("b@example.com", GOOD, full_name="B")
        other = self.client_class()
        other.login(username="b@example.com", password=GOOD)
        r = other.post(self.url, {"old_password": GOOD, "new_password1": NEW, "new_password2": NEW})
        self.assertRedirects(r, reverse("profile"))

    def test_a_success_clears_the_failure_count(self):
        for _ in range(3):
            self.change(old_password="not-it")
        self.change()
        self.assertEqual(Attempt.objects.filter(scope="password_user").count(), 0)

    def test_changing_only_accepts_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_anonymous_requests_are_sent_to_sign_in(self):
        r = self.client_class().post(
            self.url, {"old_password": GOOD, "new_password1": NEW, "new_password2": NEW}
        )
        self.assertEqual(r.status_code, 302)
        self.assertTrue(self.unchanged())


class TimeZoneTests(TestCase):
    def setUp(self):
        org = Organisation.objects.create(name="Mine", kind="government")
        self.lagos = User.objects.create_user("lagos@example.com", GOOD, full_name="L")
        self.kiri = User.objects.create_user(
            "kiri@example.com", GOOD, full_name="K", time_zone="Pacific/Kiritimati"
        )
        for user in (self.lagos, self.kiri):
            Membership.objects.create(user=user, organisation=org, role="viewer")
        self.site = Site.objects.create(
            organisation=org, name="Riverside", kind="road",
            location=Point(7.4, 9.07, srid=4326),
        )
        moment = datetime.datetime(2020, 1, 1, 10, 0, tzinfo=datetime.timezone.utc)
        with mock.patch("registry.models.timezone.now", return_value=moment):
            EvidenceEntry.objects.create(
                site=self.site, author=self.lagos, kind="note", body="Poured foundations"
            )

    def page(self, who):
        self.client.login(username=f"{who}@example.com", password=GOOD)
        return self.client.get(reverse("site_detail", args=[self.site.pk]))

    def test_times_follow_the_users_time_zone(self):
        lagos = self.page("lagos")
        self.assertContains(lagos, "01 Jan 2020")
        self.assertContains(lagos, "11:00")
        self.assertNotContains(lagos, "02 Jan 2020")
        self.client.logout()
        kiri = self.page("kiri")
        self.assertContains(kiri, "02 Jan 2020")
        self.assertContains(kiri, "00:00")
        self.assertNotContains(kiri, "01 Jan 2020")

    def test_an_invalid_stored_zone_falls_back_to_the_default(self):
        User.objects.filter(pk=self.kiri.pk).update(time_zone="Nowhere/Land")
        r = self.page("kiri")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "11:00")

    def test_a_users_zone_does_not_leak_into_the_next_request(self):
        self.page("kiri")
        self.assertEqual(dj_timezone.get_current_timezone_name(), "Africa/Lagos")
        self.client.logout()
        self.assertEqual(self.client.get(reverse("projects")).status_code, 200)
        self.assertEqual(dj_timezone.get_current_timezone_name(), "Africa/Lagos")