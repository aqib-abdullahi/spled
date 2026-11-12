import json
import math

from django.contrib.gis.geos import Polygon
from django.contrib.gis.geos.error import GEOSException

EARTH_RADIUS_M = 6371008.8
MAX_POINTS = 200
MAX_HECTARES = 100_000  # 1,000 square kilometres
MIN_HECTARES = 0.0001  # 1 square metre


def area_hectares(polygon):
    """Approximate area in hectares. Accurate enough for site-sized shapes."""
    coords = list(polygon.exterior_ring.coords)
    lat0 = sum(c[1] for c in coords) / len(coords)
    k = math.cos(math.radians(lat0))
    points = [
        (
            math.radians(c[0]) * EARTH_RADIUS_M * k,
            math.radians(c[1]) * EARTH_RADIUS_M,
        )
        for c in coords
    ]
    twice = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        twice += x1 * y2 - x2 * y1
    return abs(twice) / 2 / 10_000


def _is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def parse_boundary(raw):
    """Turn GeoJSON text into a Polygon. Returns None for empty input.
    Raises ValueError, with a message fit to show a person, if it isn't acceptable."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("The boundary couldn’t be read. Draw it again.")
    if not isinstance(data, dict) or data.get("type") != "Polygon":
        raise ValueError("The boundary must be a drawn shape.")
    rings = data.get("coordinates")
    if not isinstance(rings, list) or len(rings) != 1 or not isinstance(rings[0], list):
        raise ValueError("The boundary must be a single outline without holes.")
    ring = rings[0]
    if len(ring) < 4:
        raise ValueError("Add at least three points to draw a boundary.")
    if len(ring) > MAX_POINTS + 1:
        raise ValueError(f"Use at most {MAX_POINTS} points.")
    points = []
    for c in ring:
        if not isinstance(c, list) or len(c) != 2 or not all(_is_number(v) for v in c):
            raise ValueError("The boundary contains a point that isn’t a location.")
        lon, lat = float(c[0]), float(c[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("The boundary has a point outside the world.")
        points.append((lon, lat))
    if points[0] != points[-1]:
        raise ValueError("The boundary isn’t closed.")
    try:
        polygon = Polygon(points, srid=4326)
        valid = polygon.valid
    except (GEOSException, ValueError):
        valid = False
    if not valid:
        raise ValueError(
            "The boundary isn’t a valid shape. Check that its lines don’t cross."
        )
    hectares = area_hectares(polygon)
    if hectares < MIN_HECTARES:
        raise ValueError("The boundary is too small to be a site.")
    if hectares > MAX_HECTARES:
        raise ValueError("The boundary is too large. Draw just the site itself.")
    return polygon