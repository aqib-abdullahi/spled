from django.conf import settings

from config import map_tiles


def map_config(request):
    """Tile settings for every template. Read at request time, so tests can override."""
    return {
        "map_config": {
            "tile_url": getattr(settings, "MAP_TILE_URL", map_tiles.DEFAULT_URL),
            "attribution": getattr(settings, "MAP_TILE_ATTRIBUTION", map_tiles.DEFAULT_ATTRIBUTION),
            "max_zoom": getattr(settings, "MAP_TILE_MAX_ZOOM", map_tiles.DEFAULT_MAX_ZOOM),
            "tile_size": getattr(settings, "MAP_TILE_SIZE", map_tiles.DEFAULT_TILE_SIZE),
        }
    }