import json
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from registry import backup, crypto, offsite


class Command(BaseCommand):
    help = "Download and decrypt a database backup so restore_drill can check it."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="", help="Backup to fetch, e.g. spled-20261116T195110Z.dump (default: latest)")
        parser.add_argument("--output-dir", default="", help="Where to write the decrypted files (default: backups/restored)")

    def handle(self, *args, **options):
        key = offsite.get_key()
        remote = offsite.get_remote()
        names = offsite.backup_names(remote)
        name = options["name"] or (names[-1] if names else "")
        if not name:
            raise CommandError("There are no database backups in the off-site bucket.")
        if name not in names:
            raise CommandError(f"No backup named {name}. Available: {', '.join(names[-5:])}")

        out_dir = Path(options["output_dir"] or backup.default_dir() / "restored")
        out_dir.mkdir(parents=True, exist_ok=True)
        dump_path = out_dir / name
        manifest_path = out_dir / (name + ".json")
        if dump_path.exists() or manifest_path.exists():
            raise CommandError(f"{name} already exists in {out_dir}. Move it away or choose another --output-dir.")

        with tempfile.TemporaryDirectory() as tmp:
            enc_dump, enc_manifest = Path(tmp) / "dump.enc", Path(tmp) / "manifest.enc"
            remote.download(f"{offsite.DB_PREFIX}{name}.enc", enc_dump)
            remote.download(f"{offsite.DB_PREFIX}{name}.json.enc", enc_manifest)
            try:
                crypto.decrypt_file(enc_manifest, manifest_path, key)
                crypto.decrypt_file(enc_dump, dump_path, key)
            except crypto.CryptoError as exc:
                for leftover in (dump_path, manifest_path):
                    leftover.unlink(missing_ok=True)
                raise CommandError(str(exc))

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if backup.sha256_of(dump_path) != manifest.get("sha256"):
            for leftover in (dump_path, manifest_path):
                leftover.unlink(missing_ok=True)
            raise CommandError("The decrypted backup does not match its manifest.")

        self.stdout.write(self.style.SUCCESS(f"Backup decrypted: {dump_path}"))
        self.stdout.write(f"Next: python manage.py restore_drill {dump_path}")
        self.stdout.write("These files are NOT encrypted. Delete them when you are done.")