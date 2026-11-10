import io

from PIL import Image


def image_bytes(fmt="JPEG", size=(300, 200), mode="RGB", exif=None, color=(200, 30, 30)):
    fill = color if mode == "RGB" else (*color, 128)
    img = Image.new(mode, size, fill)
    out = io.BytesIO()
    options = {"exif": exif} if exif is not None else {}
    img.save(out, fmt, **options)
    return out.getvalue()