"""A run's trip on the day (spec section 4.3): its route's stops in their
planned order, skipping any stop where nobody is riding that day, with an
estimated arrival time at each stop that's left.

Worked out when asked, from that day's ridership (default plus overrides),
so a family's "not riding" shows up at once and nothing needs storing.

Stability (spec section 4.4): the planned order is kept, never reshuffled
on the day; only empty stops drop out. Morning times count back from the
bus reaching school at the planned time (the run's start plus its
duration), so skipping a stop can only make pickups later, never earlier,
and no student misses the bus because of someone else's absence.
Afternoon times count forward from leaving school, so skipping earlier
drop-offs brings later ones forward.

Times use the same estimate as route planning (isd_solver.routing):
straight-line travel x 1.3 at 30 km/h, and loading time per stop, rider
and accommodation.
"""

from __future__ import annotations

from dataclasses import dataclass

from isd_solver import Location, StopDemand, straight_line_travel_seconds
from sqlalchemy.orm import Session

from isd_api.models import RideDirection, RouteTemplate, Run, Student
from isd_api.routes import riders_for_run

# An arrival time this many minutes away from the plan counts as a
# material change (spec section 4.3 "notify affected riders").
MATERIAL_CHANGE_MINUTES = 5


@dataclass
class TripStop:
    position: int
    stop_id: int
    label: str
    riders: list[Student]
    skipped: bool
    # Minute of day: planned (run start + the stop's minutes from start,
    # when the route has them) and today's estimate (None when skipped).
    planned_minute: int | None
    eta_minute: int | None
    lat: float = 0.0
    lon: float = 0.0

    @property
    def materially_changed(self) -> bool:
        return (
            self.planned_minute is not None
            and self.eta_minute is not None
            and abs(self.eta_minute - self.planned_minute) >= MATERIAL_CHANGE_MINUTES
        )


def daily_trip(db: Session, run: Run, start_minute: int) -> list[TripStop] | None:
    """The run's trip today, or None when its route has no stops or its
    riders can't be attributed to it (several runs on the leg)."""
    if run.route_template_id is None:
        return None
    route = db.get(RouteTemplate, run.route_template_id)
    if route is None or not route.stops:
        return None
    riders, ambiguous = riders_for_run(db, run)
    if ambiguous:
        return None
    by_stop: dict[int, list[Student]] = {}
    for student in riders:
        if student.stop_id is not None:
            by_stop.setdefault(student.stop_id, []).append(student)

    trip = [
        TripStop(
            position=index,
            stop_id=rs.stop_id,
            label=rs.stop.label,
            riders=sorted(by_stop.get(rs.stop_id, []), key=lambda s: s.full_name),
            skipped=not by_stop.get(rs.stop_id),
            planned_minute=None
            if rs.minutes_from_start is None
            else start_minute + rs.minutes_from_start,
            eta_minute=None,
            lat=rs.stop.location_lat,
            lon=rs.stop.location_lon,
        )
        for index, rs in enumerate(route.stops, start=1)
    ]
    locations = {
        rs.stop_id: Location(rs.stop.location_lat, rs.stop.location_lon) for rs in route.stops
    }
    school = Location(run.school.location_lat, run.school.location_lon)
    travel = straight_line_travel_seconds()

    def dwell(stop: TripStop) -> int:
        return StopDemand(
            stop.stop_id,
            locations[stop.stop_id],
            riders=len(stop.riders),
            accommodation_riders=sum(1 for s in stop.riders if s.accommodations),
        ).dwell_seconds()

    active = [s for s in trip if not s.skipped]
    if run.direction == RideDirection.AM:
        # Back from reaching school at the planned time.
        next_point, next_time = school, (start_minute + run.duration_minutes) * 60
        for stop in reversed(active):
            here = locations[stop.stop_id]
            arrive = next_time - travel(here, next_point) - dwell(stop)
            stop.eta_minute = round(arrive / 60)
            next_point, next_time = here, arrive
    else:
        point, time = school, start_minute * 60
        for stop in active:
            here = locations[stop.stop_id]
            arrive = time + travel(point, here)
            stop.eta_minute = round(arrive / 60)
            point, time = here, arrive + dwell(stop)
    return trip
