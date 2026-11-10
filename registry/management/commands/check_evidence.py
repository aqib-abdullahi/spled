from django.core.management.base import BaseCommand, CommandError

from registry.models import EvidenceEntry, Site


class Command(BaseCommand):
    help = "Check every site's evidence chain, and re-read every photo against its fingerprint."

    def handle(self, *args, **options):
        bad = 0
        sites = Site.objects.order_by("id")
        for site in sites:
            problems = EvidenceEntry.verify_chain(site) + EvidenceEntry.verify_files(site)
            for entry_id, problem in problems:
                bad += 1
                self.stdout.write(
                    self.style.ERROR(f"Site {site.pk} ({site.name}), entry {entry_id}: {problem}")
                )
        if bad:
            raise CommandError(f"{bad} problem(s) found.")
        self.stdout.write(self.style.SUCCESS(f"All evidence checked. No problems in {sites.count()} site(s)."))