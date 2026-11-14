from django.core.exceptions import ImproperlyConfigured

DEFAULT_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
DEFAULT_ATTRIBUTION = (
    '© <a href="https://www.openstreetmap.org/copyright" target="_blank" '
    'rel="noopener">OpenStreetMap</a> contributors'
)
DEFAULT_MAX_ZOOM = 19
DEFAULT_TILE_SIZE = 256


def validate_tile_settings(url, attribution, max_zoom, tile_size, debug):
    """Fail at startup, not in a visitor's browser."""
    for part in ("{z}", "{x}", "{y}"):
        if part not in url:
            raise ImproperlyConfigured("MAP_TILE_URL must contain {z}, {x} and {y}.")
    if not (url.startswith("https://") or (debug and url.startswith("http://"))):
        raise ImproperlyConfigured("MAP_TILE_URL must start with https://.")
    if not attribution.strip():
        raise ImproperlyConfigured(
            "MAP_TILE_ATTRIBUTION cannot be blank. Providers require credit."
        )
    if not 1 <= max_zoom <= 22:
        raise ImproperlyConfigured("MAP_TILE_MAX_ZOOM must be between 1 and 22.")
    if tile_size not in (256, 512):
        raise ImproperlyConfigured("MAP_TILE_SIZE must be 256 or 512.")