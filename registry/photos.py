import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from django.conf import settings
from django.core import checks
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTOS = 5
MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
DISPLAY_SIZE = 1600
THUMB_SIZE = 480

Image.MAX_IMAGE_PIXELS = 60_000_000  # refuse "decompression bomb" images


class PrivateStorage(FileSystemStorage):
    """Files live outside any public folder. Only our own view serves them."""

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)


def _clean(value):
    """Pasted secrets often carry a stray space or line break. Remove it."""
    return str(value or "").strip()


def build_private_storage():
    """PHOTO_STORAGE=local keeps photos on disk (development).
    PHOTO_STORAGE=r2 keeps them in a private Cloudflare R2 bucket."""
    backend = getattr(settings, "PHOTO_STORAGE", "local")
    if backend == "local":
        return PrivateStorage()
    if backend != "r2":
        raise ImproperlyConfigured('PHOTO_STORAGE must be "local" or "r2".')

    needed = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_PHOTO_BUCKET")
    values = {name: _clean(getattr(settings, name, "")) for name in needed}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ImproperlyConfigured("PHOTO_STORAGE=r2 needs these settings: " + ", ".join(missing))
    endpoint = values["R2_ENDPOINT_URL"].rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path:
        raise ImproperlyConfigured(
            "R2_ENDPOINT_URL must look like https://<account-id>.r2.cloudflarestorage.com, "
            "with no bucket name or path after it. The bucket goes in R2_PHOTO_BUCKET."
        )
    try:
        from storages.backends.s3 import S3Storage
    except ImportError:
        raise ImproperlyConfigured(
            "PHOTO_STORAGE=r2 needs django-storages. Run: pip install -r requirements-prod.txt"
        )
    return S3Storage(
        access_key=values["R2_ACCESS_KEY_ID"],
        secret_key=values["R2_SECRET_ACCESS_KEY"],
        bucket_name=values["R2_PHOTO_BUCKET"],
        endpoint_url=endpoint,
        region_name="auto",
        signature_version="s3v4",
        default_acl=None,
        file_overwrite=False,
        querystring_auth=True,
    )

_storage = build_private_storage()

def private_storage():
    return _storage

@checks.register(checks.Tags.security, deploy=True)
def check_photo_storage(App_configs, **kwargs):
    """shown by `manage.py check -deploy`."""
    if not settings.DEBUG and getattr(settings, "PHOTO_STORAGE", "local") == "local":
        return [
            checks.Warning(
                "Evidence photos are stored on this server's local disk.",
                hint=(
                    "Hosts that restart or redeploy lose local files, so photos would "
                    "disappear while their fingerprints stay in the record. "
                    "Set PHOTO_STORAGE=r2, or attach a persistent disk."
                ),
                id="spled.W001",
            )
        ]
    return []

def check_photo_file(photo):
    """Compare a photo's stored original with its fingerprint.
    Returns a problem description, or None if the file is fine."""
    try:
        with photo.original.open("rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
    except FileNotFoundError:
        return f"photo {photo.id} file missing"
    except Exception as exc:  # network or storage trouble is not the same as "missing"
        return f"photo {photo.id} could not be read ({type(exc).__name__})"
    if digest != photo.sha256:
        return f"photo {photo.id} file changed"
    return None

def photo_upload_path(instance, filename):
    return f"evidence/{instance.entry.site_id}/{uuid.uuid4().hex}-{os.path.basename(filename)}"


class PhotoError(ValueError):
    pass


@dataclass
class Processed:
    original: bytes
    sha256: str
    ext: str
    width: int
    height: int
    display: bytes
    thumb: bytes


def _flatten(img):
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return img.convert("RGB")


def _encode(img, size):
    copy = img.copy()
    copy.thumbnail((size, size), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    copy.save(out, "JPEG", quality=85, optimize=True)  # no EXIF is written
    return out.getvalue()


def process_image(uploaded):
    data = uploaded.read()
    if not data:
        raise PhotoError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise PhotoError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise PhotoError("This isn’t a readable image.")
    if fmt not in ALLOWED:
        raise PhotoError("Use a JPEG, PNG or WebP photo.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            img = _flatten(img)
            display = _encode(img, DISPLAY_SIZE)
            thumb = _encode(img, THUMB_SIZE)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise PhotoError("This image couldn’t be processed.")
    return Processed(
        original=data,
        sha256=hashlib.sha256(data).hexdigest(),
        ext=ALLOWED[fmt],
        width=width,
        height=height,
        display=display,
        thumb=thumb,
    )