"""Temporary road closures (spec section 10 "dynamic rerouting"): which are
in force, and which runs they may affect.

A closure is in force from `starts_at` until `ends_at` (or open-ended)
unless it has been cleared. Directions and the scheduler's travel times
avoid it; this module also finds the runs to warn about.

A run "may be affected" when its trip for the day passes near a closure:
this system has no road geometry for a route until directions are asked
for, so the check follows the straight lines between the day's stops and
the school, with `ROUTE_BUFFER_M` of slack for roads that don't run
straight. A stop inside a closure is worse: the bus can't reach it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from isd_api import ridership_rules
from isd_api.daily_trip import daily_trip
from isd_api.i18n import tr
from isd_api.models import Assignment, RideDirection, RoadClosure, Run

ROUTE_BUFFER_M = 250
KIND_LABELS = {
    "road_closed": "road closed",
    "collision": "collision",
    "construction": "construction",
    "flooding": "flooding",
    "police_activity": "police activity",
    "severe_congestion": "severe congestion",
    "other": "closure",
}


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def in_force(db: Session, start: datetime, end: datetime) -> list[RoadClosure]:
    """Closures in force at any time in [start, end)."""
    rows = (
        db.query(RoadClosure)
        .filter(
            RoadClosure.cleared_at.is_(None),
            or_(RoadClosure.ends_at.is_(None), RoadClosure.ends_at > start),
        )
        .order_by(RoadClosure.id)
        .all()
    )
    return [
        c
        for c in rows
        if _utc(c.starts_at) < end and (c.ends_at is None or _utc(c.ends_at) > start)
    ]


def active_now(db: Session, now: datetime | None = None) -> list[RoadClosure]:
    now = now or ridership_rules.utc_now()
    return in_force(db, now, now + timedelta(seconds=1))


def for_service_date(db: Session, service_date: date) -> list[RoadClosure]:
    """Closures in force at any time on the district's `service_date`."""
    rules = ridership_rules.load_rules(db)
    tz = ridership_rules.district_now(rules).tzinfo
    start = datetime.combine(service_date, time.min, tzinfo=tz).astimezone(UTC)
    return in_force(db, start, start + timedelta(days=1))


def _metres_to_segment(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance in metres from point p to segment ab, all (lat, lon), on a
    local flat projection (fine over a school route's few miles)."""
    lat0 = math.radians(p[0])

    def xy(q: tuple[float, float]) -> tuple[float, float]:
        return ((q[1] - p[1]) * 111_320 * math.cos(lat0), (q[0] - p[0]) * 111_320)

    (ax, ay), (bx, by) = xy(a), xy(b)
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx, cy)


@dataclass(frozen=True)
class Impact:
    closure: RoadClosure
    # A stop on the day's trip that's inside the closure, if any.
    stop_inside: str | None


def impacts(db: Session, assignment: Assignment, closures: list[RoadClosure]) -> list[Impact]:
    """The closures a run's trip for the day passes near."""
    if not closures:
        return []
    run: Run = assignment.run
    trip = [s for s in daily_trip(db, run, assignment.start_minute) or [] if not s.skipped]
    school = (run.school.location_lat, run.school.location_lon)
    points = [(s.lat, s.lon) for s in trip]
    path = [*points, school] if run.direction == RideDirection.AM else [school, *points]
    found: list[Impact] = []
    for closure in closures:
        centre = (closure.location_lat, closure.location_lon)
        inside = next(
            (
                s.label
                for s in trip
                if _metres_to_segment(centre, (s.lat, s.lon), (s.lat, s.lon)) <= closure.radius_m
            ),
            None,
        )
        near = (
            any(
                _metres_to_segment(centre, a, b) <= closure.radius_m + ROUTE_BUFFER_M
                for a, b in zip(path, path[1:], strict=False)
            )
            if len(path) > 1
            else False
        )
        if inside is not None or near:
            found.append(Impact(closure, inside))
    return found


def describe(closure: RoadClosure, lang: str = "en") -> str:
    """The kind, in `lang`, and staff's note as they wrote it."""
    kind = KIND_LABELS.get(closure.kind.value, "closure")
    return f"{tr(lang, kind)}: {closure.note}"
