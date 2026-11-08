from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from accounts.models import User
from organisations.models import Membership, Organisation

from ...models import EvidenceEntry, Site

SITES = [
    ("Northern Ring Road, Section 2", "road", "delayed", "Works Dept", 54, (7.3951, 9.1002)),
    ("Riverside Solar Mini-Grid", "power", "in_progress", "Energy Agency", 71, (7.3986, 9.0765)),
    ("District Clinic, Block C", "building", "in_progress", "Health Ministry", 88, (7.4302, 9.0554)),
    ("Irrigation Canal Lining", "agriculture", "stalled", "Water Board", 23, (7.3505, 9.0318)),
    ("Market Drainage Upgrade", "infrastructure", "planned", "Works Dept", 0, (7.4811, 9.0720)),
    ("Primary School Wing", "building", "complete", "Education Board", 100, (7.4410, 9.1103)),
]


class Command(BaseCommand):
    help = "Create demo data for local development: python manage.py seed_demo you@example.com"

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, email, **options):
        user = User.objects.get(email__iexact=email)
        org, created = Organisation.objects.get_or_create(
            name="Energy Agency (demo)",
            defaults={"kind": "government", "verification": "verified"},
        )
        Membership.objects.get_or_create(
            user=user, organisation=org, defaults={"role": "admin"}
        )
        if not created:
            self.stdout.write("Demo data already exists, nothing added.")
            return
        for name, kind, status, owner, progress, (lon, lat) in SITES:
            site = Site.objects.create(
                organisation=org, name=name, kind=kind, status=status,
                owner_name=owner, progress=progress,
                location=Point(lon, lat, srid=4326), created_by=user,
            )
            if status in ("in_progress", "delayed", "complete"):
                EvidenceEntry.objects.create(
                    site=site, author=user, kind="check_in",
                    body="Site visit completed.",
                    location=Point(lon + 0.0002, lat + 0.0002, srid=4326),
                )
        self.stdout.write(self.style.SUCCESS("Demo organisation and six sites created."))