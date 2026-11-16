import io
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from registry import backup, offsite


class Command(BaseCommand):
    help = "Back up the database and evidence photos to the off-site bucket, encrypted."

    def add_arguments(self, parser):
        parser.add_argument("--skip-photos", action="store_true", help="Only back up the database")
        parser.add_argument("--keep-local", action="store_true",
                            help="Also keep the unencrypted dump in the backups folder")

    def handle(self, *args, **options):
        key = offsite.get_key()      # check the setup before doing any work
        remote = offsite.get_remote()

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            plain_dir = backup.default_dir() if options["keep_local"] else tmp / "plain"
            call_command("backup_db", output_dir=str(plain_dir), stdout=io.StringIO())
            dumps = sorted(plain_dir.glob("spled-*.dump"))
            if not dumps:
                raise CommandError("The database backup was not created.")
            encrypted = tmp / "encrypted"
            encrypted.mkdir()
            name = offsite.upload_backup(remote, key, dumps[-1], encrypted)
        self.stdout.write(self.style.SUCCESS(f"Database backup uploaded, encrypted: {name}"))

        if options["skip_photos"]:
            return
        result = offsite.push_photos(remote, key, offsite.photo_rows())
        self.stdout.write(
            f"Photos: {result['uploaded']} uploaded, {result['already']} already backed up."
        )
        if result["problems"]:
            for problem in result["problems"][:10]:
                self.stdout.write(self.style.ERROR(problem))
            raise CommandError(f"{len(result['problems'])} photo problem(s). The database backup was uploaded.")