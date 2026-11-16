from django.core.management.base import BaseCommand

from registry import backup


class Command(BaseCommand):
    help = "Restore a backup into a scratch database, check it, then remove the scratch database."

    def add_arguments(self, parser):
        parser.add_argument("dump", help="Path to a .dump file made by backup_db")
        parser.add_argument("--keep", action="store_true", help="Keep the scratch database afterwards")

    def handle(self, *args, **options):
        backup.run_drill(options["dump"], keep=options["keep"], log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS("Restore drill PASSED: the backup restores and verifies."))