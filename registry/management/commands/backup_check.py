from django.core.management.base import BaseCommand, CommandError

from registry import offsite


class Command(BaseCommand):
    help = "Check the off-site bucket: a recent database backup, and a backup of every photo."

    def add_arguments(self, parser):
        parser.add_argument("--deep", action="store_true",
                            help="Download and decrypt every photo copy and compare its fingerprint")
        parser.add_argument("--max-age-hours", type=float, default=None,
                            help="Fail if the newest database backup is older than this")

    def handle(self, *args, **options):
        deep = options["deep"]
        key = offsite.get_key() if deep else None
        remote = offsite.get_remote()

        names = offsite.backup_names(remote)
        if not names:
            raise CommandError("There are no database backups in the off-site bucket.")
        latest = names[-1]
        age = offsite.backup_age_hours(latest)
        problems = []
        if age is None:
            self.stdout.write(f"Latest database backup: {latest}")
        else:
            self.stdout.write(f"Latest database backup: {latest} ({age:.1f} hours old)")
            limit = options["max_age_hours"]
            if limit is not None and age > limit:
                problems.append(f"the latest database backup is {age:.1f} hours old; the limit is {limit:g}")

        total, photo_problems = offsite.check_photos(remote, key, offsite.photo_hashes(), deep=deep)
        problems += photo_problems
        good = total - len(photo_problems)
        self.stdout.write(f"Photos: {good} of {total} backed up{' and verified' if deep else ''}.")

        if problems:
            for problem in problems[:10]:
                self.stdout.write(self.style.ERROR(problem))
            raise CommandError(f"{len(problems)} problem(s) found.")
        self.stdout.write(self.style.SUCCESS("Off-site backups verified."))