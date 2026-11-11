from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from organisations.models import Organisation

from .milestones import recompute_progress
from .models import Milestone, Site


class MilestoneModelTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Org", kind="government")
        self.site = Site.objects.create(
            organisation=self.org, name="Road", kind="road", progress=40,
            location=Point(7.4, 9.07, srid=4326),
        )

    def milestone(self, title, position=0, done=False):
        return Milestone.objects.create(
            site=self.site, title=title, position=position,
            completed_at=timezone.now() if done else None,
        )

    def follow(self):
        Site.objects.filter(pk=self.site.pk).update(progress_from_milestones=True)
        self.site.refresh_from_db()

    def test_milestones_are_ordered_by_position(self):
        self.milestone("c", position=2)
        self.milestone("a", position=0)
        self.milestone("b", position=1)
        titles = list(self.site.milestones.values_list("title", flat=True))
        self.assertEqual(titles, ["a", "b", "c"])

    def test_progress_is_unchanged_when_not_following(self):
        self.milestone("a", done=True)
        recompute_progress(self.site)
        self.site.refresh_from_db()
        self.assertEqual(self.site.progress, 40)

    def test_progress_follows_the_share_done(self):
        self.follow()
        first = self.milestone("a", 0, done=True)
        second = self.milestone("b", 1)
        third = self.milestone("c", 2)
        recompute_progress(self.site)
        self.site.refresh_from_db()
        self.assertEqual(self.site.progress, 33)
        Milestone.objects.filter(pk=second.pk).update(completed_at=timezone.now())
        recompute_progress(self.site)
        self.site.refresh_from_db()
        self.assertEqual(self.site.progress, 67)
        Milestone.objects.filter(pk=third.pk).update(completed_at=timezone.now())
        recompute_progress(self.site)
        self.site.refresh_from_db()
        self.assertEqual(self.site.progress, 100)

    def test_no_milestones_gives_zero(self):
        self.follow()
        recompute_progress(self.site)
        self.site.refresh_from_db()
        self.assertEqual(self.site.progress, 0)