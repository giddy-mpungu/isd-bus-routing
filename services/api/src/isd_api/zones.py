"""School attendance zones (spec section 3: students are assigned using
"attendance zone"): each school's boundary, imported as GeoJSON from the
district's GIS, and whether a home lies inside it.

Only Polygon and MultiPolygon geometries, in longitude/latitude (GeoJSON's
order); holes are respected. A Feature or a one-feature FeatureCollection
is accepted and reduced to its geometry.
"""

from __future__ import annotations

from typing import Any

MAX_POINTS = 50_000


class ZoneError(ValueError):
    """The upload isn't a usable boundary; the message says why."""


def _ring(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, list) or len(raw) < 4:
        raise ZoneError("Each boundary ring needs at least four points")
    ring = []
    for point in raw:
        if not (isinstance(point, list) and len(point) >= 2):
            raise ZoneError("Each point must be [longitude, latitude]")
        lon, lat = point[0], point[1]
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lon, lat)):
            raise ZoneError("Each point must be [longitude, latitude]")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ZoneError("A point is outside longitude/latitude range")
        ring.append((float(lon), float(lat)))
    return ring


def geometry_from_upload(data: Any) -> dict:
    """The Polygon/MultiPolygon geometry in an uploaded GeoJSON object."""
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = data.get("features") or []
        if len(features) != 1:
            raise ZoneError("Upload one school's boundary: a single feature")
        data = features[0]
    if isinstance(data, dict) and data.get("type") == "Feature":
        data = data.get("geometry")
    if not isinstance(data, dict) or data.get("type") not in ("Polygon", "MultiPolygon"):
        raise ZoneError("The boundary must be a GeoJSON Polygon or MultiPolygon")
    polygons = [data.get("coordinates")] if data["type"] == "Polygon" else data.get("coordinates")
    if not isinstance(polygons, list) or not polygons:
        raise ZoneError("The boundary has no coordinates")
    count = 0
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ZoneError("The boundary has an empty polygon")
        for ring in polygon:
            count += len(_ring(ring))
    if count > MAX_POINTS:
        raise ZoneError(f"The boundary has more than {MAX_POINTS} points; simplify it first")
    return {"type": data["type"], "coordinates": data["coordinates"]}


def _in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=False):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def contains(geometry: dict, lat: float, lon: float) -> bool:
    """Whether the point lies inside the zone (inside an outer ring and
    in none of that polygon's holes)."""
    polygons = (
        [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    )
    for polygon in polygons:
        outer, *holes = (_ring(r) for r in polygon)
        if _in_ring(lon, lat, outer) and not any(_in_ring(lon, lat, h) for h in holes):
            return True
    return False
