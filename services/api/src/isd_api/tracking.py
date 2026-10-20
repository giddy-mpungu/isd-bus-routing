"""Live tracking from the tablets' GPS (spec section 9 "direction of
travel", "route deviation"; section 20 history): which way a bus is
heading, and how far it is from its route.

A route here is the day's trip drawn as straight lines between its stops
and the school (`daily_trip`), not the roads, so "off route" is generous
(`OFF_ROUTE_METERS`): a bus well away from every leg of its route, not one
taking a different street.
"""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from isd_api.daily_trip import daily_trip
from isd_api.models import Assignment, PositionSample, RideDirection

# A bus farther than this from every leg of its route is off route.
OFF_ROUTE_METERS = 800
# Samples closer together than this are GPS jitter, not movement.
MIN_MOVE_METERS = 30
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_EARTH_M = 6_371_000


def _xy(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    """Metres east/north on a flat projection around latitude `lat0`."""
    return (
        math.radians(lon) * _EARTH_M * math.cos(math.radians(lat0)),
        math.radians(lat) * _EARTH_M,
    )


def bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Degrees clockwise from north, going from point a to point b."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    x = math.sin(lon2 - lon1) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass(degrees: float) -> str:
    return _COMPASS[int((degrees + 22.5) // 45) % 8]


def heading(db: Session, crew_id: int) -> float | None:
    """Which way the crew's bus is going, from its latest GPS samples, or
    None when it hasn't moved far enough to tell."""
    samples = (
        db.query(PositionSample)
        .filter(PositionSample.crew_id == crew_id)
        .order_by(PositionSample.recorded_at.desc())
        .limit(10)
        .all()
    )
    if not samples:
        return None
    latest = samples[0]
    here = (latest.location_lat, latest.location_lon)
    for earlier in samples[1:]:
        there = (earlier.location_lat, earlier.location_lon)
        if distance_m(there, here) >= MIN_MOVE_METERS:
            return bearing(there, here)
    return None


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = _xy(*a, a[0])
    bx, by = _xy(*b, a[0])
    return math.hypot(bx - ax, by - ay)


def route_line(db: Session, assignment: Assignment) -> list[tuple[float, float]]:
    """The run's route today: stops in order (skipped ones left out) and the
    school, at the end in the morning and the start in the afternoon."""
    run = assignment.run
    stops = [
        (s.lat, s.lon) for s in daily_trip(db, run, assignment.start_minute) or [] if not s.skipped
    ]
    school = (run.school.location_lat, run.school.location_lon)
    return [*stops, school] if run.direction == RideDirection.AM else [school, *stops]


def distance_from_line(point: tuple[float, float], line: list[tuple[float, float]]) -> float:
    """Metres from `point` to the nearest leg of `line`."""
    if not line:
        return math.inf
    lat0 = point[0]
    px, py = _xy(*point, lat0)
    xy = [_xy(lat, lon, lat0) for lat, lon in line]
    if len(xy) == 1:
        return math.hypot(xy[0][0] - px, xy[0][1] - py)
    best = math.inf
    for (ax, ay), (bx, by) in zip(xy, xy[1:], strict=False):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
        best = min(best, math.hypot(ax + t * dx - px, ay + t * dy - py))
    return best


def off_route_m(db: Session, assignment: Assignment, point: tuple[float, float]) -> float | None:
    """How far `point` is from the run's route today, in metres, or None
    when the route has no stops to draw (nothing to be off)."""
    line = route_line(db, assignment)
    if len(line) < 2:
        return None
    return distance_from_line(point, line)
