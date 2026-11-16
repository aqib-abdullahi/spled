import uuid

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from registry.photos import private_storage


class Command(BaseCommand):
    help = "Write, read back and delete a small test file through the photo storage."

    def handle(self, *args, **options):
        storage = private_storage()
        backend = type(storage).__name__
        bucket = getattr(storage, "bucket_name", "")
        where = f"{backend}, bucket {bucket}" if bucket else backend
        payload = ("spled storage check " + uuid.uuid4().hex).encode()
        name = None
        try:
            name = storage.save(f"healthcheck/{uuid.uuid4().hex}.txt", ContentFile(payload))
            with storage.open(name, "rb") as handle:
                data = handle.read()
        except Exception as exc:
            raise CommandError(f"Photo storage failed ({where}): {type(exc).__name__}: {exc}")
        finally:
            if name:
                try:
                    storage.delete(name)
                except Exception:
                    self.stderr.write("Could not delete the test file " + name)
        if data != payload:
            raise CommandError(f"Photo storage returned different data than was written ({where}).")
        self.stdout.write(self.style.SUCCESS(
            f"Photo storage works ({where}): wrote, read back and deleted a test file."
        ))