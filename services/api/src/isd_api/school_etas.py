"""When each bus is expected at the school (spec section 17, school
administrators: "expected arrivals", "delayed buses").

Morning: when the bus reaches school (planned: the run's start plus its
duration). Afternoon: when it leaves school for dismissal (planned: the
run's start). Live only for the district's today; any other day shows the
plan.

  - Finished (morning completed, or afternoon under way or done): that's
    what happened, not an estimate.
  - Under way with GPS no older than GPS_STALE_MINUTES (morning only):
    now, plus the estimated drive from the bus's position through the
    day's remaining stops (isd_api/daily_trip.py) to school.
  - Not under way after its start time: late by at least the time since,
    so the plan moved later by that much.
  - Otherwise: the plan.

Estimates use route planning's travel and loading model. The expected
time is never shown as earlier than planned (a bus doesn't leave early),
and `delay_minutes` is how much later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from isd_solver import Location, StopDemand, straight_line_travel_seconds
from sqlalchemy.orm import Session

from isd_api import ridership_rules
from isd_api.assignment_states import TERMINAL, UNDERWAY
from isd_api.daily_trip import daily_trip
from isd_api.models import Assignment, AssignmentStatus, RideDirection, VehiclePosition

GPS_STALE_MINUTES = 5
# A bus this many minutes behind the plan counts as late on the page.
LATE_MINUTES = 5


@dataclass(frozen=True)
class SchoolEta:
    planned_minute: int
    expected_minute: int
    delay_minutes: int
    # How the expected time was worked out, in words for the page.
    basis: str


def _local(moment: datetime, rules: ridership_rules.Rules) -> datetime:
    moment = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return ridership_rules.district_now(rules, moment)


def school_eta(db: Session, assignment: Assignment, now: datetime | None = None) -> SchoolEta:
    run = assignment.run
    am = run.direction == RideDirection.AM
    planned = assignment.start_minute + (run.duration_minutes if am else 0)

    def result(expected: int, basis: str) -> SchoolEta:
        expected = max(expected, planned)
        return SchoolEta(planned, expected, expected - planned, basis)

    rules = ridership_rules.load_rules(db)
    now = now or ridership_rules.utc_now()
    local_now = ridership_rules.district_now(rules, now)
    if run.service_date != local_now.date():
        return result(planned, "Planned")
    now_minute = local_now.hour * 60 + local_now.minute
    status = assignment.status

    if am and status == AssignmentStatus.COMPLETED:
        if assignment.status_updated_at is not None:
            local = _local(assignment.status_updated_at, rules)
            done = local.hour * 60 + local.minute
            return SchoolEta(planned, done, max(0, done - planned), "Arrived")
        return result(planned, "Arrived")
    if not am and (status in UNDERWAY or status in TERMINAL):
        return result(planned, "Left school")

    if am and status in UNDERWAY:
        position = (
            db.query(VehiclePosition)
            .filter(VehiclePosition.crew_id == assignment.crew_id)
            .one_or_none()
        )
        if position is not None:
            recorded = position.recorded_at
            recorded = recorded if recorded.tzinfo is not None else recorded.replace(tzinfo=UTC)
            if (now - recorded).total_seconds() <= GPS_STALE_MINUTES * 60:
                return result(
                    now_minute + _minutes_to_school(db, assignment, position),
                    "Live GPS",
                )

    if status not in UNDERWAY and status not in TERMINAL and now_minute > assignment.start_minute:
        return result(planned + (now_minute - assignment.start_minute), "Not started yet")
    return result(planned, "On plan")


def _minutes_to_school(db: Session, assignment: Assignment, position: VehiclePosition) -> int:
    """From the bus's position, through the stops still ahead today, to
    school. Which stops are ahead is judged by where the bus is, not by the
    clock (a late bus hasn't passed stops just because their time has):
    from the stop nearest the bus onwards, leaving that one out when the
    bus is already closer to school than it is."""
    run = assignment.run
    travel = straight_line_travel_seconds()
    school = Location(run.school.location_lat, run.school.location_lon)
    here = Location(position.location_lat, position.location_lon)
    active = [s for s in daily_trip(db, run, assignment.start_minute) or [] if not s.skipped]
    ahead = []
    if active:
        nearest = min(
            range(len(active)),
            key=lambda i: travel(here, Location(active[i].lat, active[i].lon)),
        )
        nearest_stop = Location(active[nearest].lat, active[nearest].lon)
        if travel(here, school) < travel(nearest_stop, school):
            nearest += 1
        ahead = active[nearest:]
    seconds = 0
    for stop in ahead:
        rs_location = Location(stop.lat, stop.lon)
        seconds += (
            travel(here, rs_location)
            + StopDemand(
                stop.stop_id,
                rs_location,
                riders=len(stop.riders),
                accommodation_riders=sum(1 for s in stop.riders if s.accommodations),
            ).dwell_seconds()
        )
        here = rs_location
    seconds += travel(here, school)
    return round(seconds / 60)
