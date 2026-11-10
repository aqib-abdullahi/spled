import hashlib
import io
import os
import uuid
from dataclasses import dataclass

from django.conf import settings
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


_storage = PrivateStorage()


def private_storage():
    return _storage


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