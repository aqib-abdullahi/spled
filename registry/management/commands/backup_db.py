from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from registry import backup


class Command(BaseCommand):
    help = "Dump the database to a file, with a manifest (checksum, row counts) beside it."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="", help="Where to write the backup (default: backups/)")

    def handle(self, *args, **options):
        out_dir = Path(options["output_dir"] or backup.default_dir())
        out_dir.mkdir(parents=True, exist_ok=True)
        dump = out_dir / f"spled-{backup.utc_stamp()}.dump"
        if dump.exists():
            raise CommandError(f"{dump.name} already exists. Wait a second and try again.")

        parts = backup.connection_parts()
        command = [
            backup.find_tool("pg_dump"), *backup.host_args(parts), "--no-password",
            "--format=custom", "--no-owner", "--no-acl", "--file", str(dump), parts["dbname"],
        ]
        try:
            backup.run_tool(command, backup.tool_env(parts))
        except CommandError:
            dump.unlink(missing_ok=True)  # never leave a half-written backup behind
            raise

        manifest = backup.make_manifest(dump, parts)
        self.stdout.write(self.style.SUCCESS(f"Backup written: {dump}"))
        self.stdout.write(f"  size: {manifest['size_bytes']:,} bytes")
        self.stdout.write(f"  sha256: {manifest['sha256']}")
        for key, value in manifest["counts"].items():
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write("This file contains everything, including password hashes. Keep it private.")