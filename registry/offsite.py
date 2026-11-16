import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import CommandError

from registry import crypto
from registry.backup import sha256_of

DB_PREFIX = "db/"
PHOTO_PREFIX = "photos/"
NAME_FORMAT = "spled-%Y%m%dT%H%M%SZ.dump"


def _clean(value):
    return str(value or "").strip()


def get_key():
    try:
        return crypto.parse_key(getattr(settings, "BACKUP_ENCRYPTION_KEY", ""))
    except crypto.CryptoError as exc:
        raise CommandError(str(exc))


def remote_settings():
    names = ("R2_ENDPOINT_URL", "R2_BACKUP_ACCESS_KEY_ID", "R2_BACKUP_SECRET_ACCESS_KEY", "R2_BACKUP_BUCKET")
    values = {name: _clean(getattr(settings, name, "")) for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise CommandError("Off-site backups need these settings: " + ", ".join(missing))
    endpoint = values["R2_ENDPOINT_URL"].rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path:
        raise CommandError(
            "R2_ENDPOINT_URL must look like https://<account-id>.r2.cloudflarestorage.com, "
            "with no bucket name after it."
        )
    if values["R2_BACKUP_BUCKET"] == _clean(getattr(settings, "R2_PHOTO_BUCKET", "")):
        raise CommandError(
            "R2_BACKUP_BUCKET must be a different bucket from R2_PHOTO_BUCKET: "
            "a backup kept beside the original is lost with it."
        )
    values["R2_ENDPOINT_URL"] = endpoint
    return values


class Remote:
    """A small wrapper so the commands never touch boto3 directly."""

    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket

    def _call(self, action, fn):
        try:
            return fn()
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Off-site storage failed while {action} ({type(exc).__name__}: {exc})")

    def upload(self, path, key):
        self._call(f"uploading {key}", lambda: self.client.upload_file(str(path), self.bucket, key))

    def download(self, key, path):
        self._call(f"downloading {key}", lambda: self.client.download_file(self.bucket, key, str(path)))

    def exists(self, key):
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in ("404", "NoSuchKey", "NotFound"):
                return False
            raise CommandError(f"Off-site storage failed while checking {key} ({code})")

    def keys(self, prefix):
        def listing():
            found = []
            for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
                found.extend(item["Key"] for item in page.get("Contents", []))
            return sorted(found)

        return self._call(f"listing {prefix}", listing)


def get_remote():
    values = remote_settings()
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        raise CommandError("Off-site backups need boto3. Run: pip install -r requirements-prod.txt")
    client = boto3.client(
        "s3",
        endpoint_url=values["R2_ENDPOINT_URL"],
        aws_access_key_id=values["R2_BACKUP_ACCESS_KEY_ID"],
        aws_secret_access_key=values["R2_BACKUP_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )
    return Remote(client, values["R2_BACKUP_BUCKET"])


# ---------- database backups ----------

def upload_backup(remote, key, dump, workdir):
    """Encrypt and upload a dump and its manifest. The manifest goes last, so a
    backup only appears in listings once it is complete."""
    dump = Path(dump)
    manifest = Path(str(dump) + ".json")
    if not manifest.is_file():
        raise CommandError(f"The manifest next to {dump.name} is missing.")
    enc_dump = Path(workdir) / (dump.name + ".enc")
    enc_manifest = Path(workdir) / (dump.name + ".json.enc")
    crypto.encrypt_file(dump, enc_dump, key)
    crypto.encrypt_file(manifest, enc_manifest, key)
    remote.upload(enc_dump, f"{DB_PREFIX}{dump.name}.enc")
    remote.upload(enc_manifest, f"{DB_PREFIX}{dump.name}.json.enc")
    return dump.name


def backup_names(remote):
    names = []
    for key in remote.keys(DB_PREFIX):
        if key.endswith(".dump.json.enc"):
            names.append(key[len(DB_PREFIX):-len(".json.enc")])
    return sorted(names)


def backup_age_hours(name):
    try:
        when = datetime.strptime(name, NAME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600


# ---------- photos ----------

def photo_rows():
    from registry.models import EvidencePhoto

    return EvidencePhoto.objects.all().iterator()


def photo_hashes():
    from registry.models import EvidencePhoto

    return list(EvidencePhoto.objects.values_list("sha256", flat=True))


def push_photos(remote, key, rows):
    existing = set(remote.keys(PHOTO_PREFIX))
    uploaded = already = 0
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        plain, enc = Path(tmp) / "photo", Path(tmp) / "photo.enc"
        for photo in rows:
            object_key = f"{PHOTO_PREFIX}{photo.sha256}.enc"
            if object_key in existing:
                already += 1
                continue
            try:
                with photo.original.open("rb") as handle:
                    data = handle.read()
            except FileNotFoundError:
                problems.append(f"photo {photo.id} file missing")
                continue
            except Exception as exc:
                problems.append(f"photo {photo.id} could not be read ({type(exc).__name__})")
                continue
            if hashlib.sha256(data).hexdigest() != photo.sha256:
                problems.append(f"photo {photo.id} file changed: not backed up")
                continue
            plain.write_bytes(data)
            crypto.encrypt_file(plain, enc, key)
            remote.upload(enc, object_key)
            existing.add(object_key)
            uploaded += 1
    return {"uploaded": uploaded, "already": already, "problems": problems}


def check_photos(remote, key, shas, deep=False):
    existing = set(remote.keys(PHOTO_PREFIX))
    wanted = sorted(set(shas))
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        enc, plain = Path(tmp) / "photo.enc", Path(tmp) / "photo"
        for sha in wanted:
            object_key = f"{PHOTO_PREFIX}{sha}.enc"
            if object_key not in existing:
                problems.append(f"no backup of the photo with fingerprint {sha[:12]}...")
                continue
            if not deep:
                continue
            try:
                remote.download(object_key, enc)
                crypto.decrypt_file(enc, plain, key)
            except crypto.CryptoError:
                problems.append(f"the backup copy of photo {sha[:12]}... is damaged, or the key is wrong")
                continue
            if sha256_of(plain) != sha:
                problems.append(f"the backup copy of photo {sha[:12]}... does not match its fingerprint")
    return len(wanted), problems