"""Driver work-hour rules outside the solver (spec section 2.1), each off
until the district sets it (Setup, Rules & optimization): checks for a
manual reassignment and a field-trip assignment, and the rest-between-days
rule, which narrows a crew's availability window before solving.

The solver itself enforces the daily duty limit and breaks
(`isd_solver.WorkRules`); these mirror it for paths that don't go through
the solver. Travel time between runs isn't known here, so a gap counts as
a break by the clock alone.
"""

from __future__ import annotations

from datetime import date, timedelta

from isd_solver import WorkRules
from sqlalchemy.orm import Session

from isd_api.availability import trips_blocking
from isd_api.models import Assignment, Crew

DAY = 24 * 60


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def day_work(
    db: Session,
    driver_id: int,
    service_date: date,
    *,
    exclude_assignment_id: int | None = None,
    exclude_trip_id: int | None = None,
) -> list[tuple[int, int]]:
    """The driver's runs and field trips that day, as (start, end) minutes."""
    intervals = [
        (a.start_minute, a.end_minute)
        for a in db.query(Assignment)
        .join(Crew, Assignment.crew_id == Crew.id)
        .filter(Crew.driver_id == driver_id, Crew.service_date == service_date)
        if a.id != exclude_assignment_id
    ]
    intervals += [
        (start, end)
        for _, start, end in trips_blocking(
            db, service_date, driver_id=driver_id, exclude_trip_id=exclude_trip_id
        )
    ]
    return sorted(intervals)


def day_problem(
    work: list[tuple[int, int]], driver_limit: int | None, rules: WorkRules
) -> str | None:
    """Why a driver's day breaks the duty limit or the break rule, or None."""
    if not work:
        return None
    work = sorted(work)
    limits = [m for m in (driver_limit, rules.max_duty_minutes) if m]
    span = max(e for _, e in work) - work[0][0]
    if limits and span > min(limits):
        return (
            f"the driver would be on duty {span} minutes ({_hhmm(work[0][0])}-"
            f"{_hhmm(max(e for _, e in work))}), over the limit of {min(limits)}"
        )
    if rules.breaks:
        allowed, rest = rules.break_after_minutes or 0, rules.break_minutes or 0
        stretch_start, stretch_end = work[0]
        for start, end in [*work[1:], (DAY * 2, DAY * 2)]:
            if start - stretch_end >= rest:
                if stretch_end - stretch_start > allowed:
                    return (
                        f"the driver would work {stretch_end - stretch_start} minutes "
                        f"({_hhmm(stretch_start)}-{_hhmm(stretch_end)}) without a "
                        f"{rest}-minute break; the district allows {allowed}"
                    )
                stretch_start = start
            stretch_end = max(stretch_end, end)
    return None


def _edge(db: Session, driver_id: int, service_date: date, last: bool) -> int | None:
    work = day_work(db, driver_id, service_date)
    if not work:
        return None
    return max(e for _, e in work) if last else work[0][0]


def rest_window(
    db: Session,
    driver_id: int,
    service_date: date,
    earliest: int,
    latest: int,
    min_rest: int | None,
) -> tuple[int, int]:
    """The crew's availability window narrowed so the driver gets
    `min_rest` minutes off after the previous day and before the next."""
    if not min_rest:
        return earliest, latest
    before = _edge(db, driver_id, service_date - timedelta(days=1), last=True)
    after = _edge(db, driver_id, service_date + timedelta(days=1), last=False)
    if before is not None:
        earliest = max(earliest, before + min_rest - DAY)
    if after is not None:
        latest = min(latest, after - min_rest + DAY)
    return earliest, latest


def rest_problem(
    db: Session,
    driver_id: int,
    service_date: date,
    start: int,
    end: int,
    min_rest: int | None,
) -> str | None:
    """Why work from `start` to `end` that day leaves the driver too little
    rest after the previous day or before the next, or None."""
    earliest, latest = rest_window(db, driver_id, service_date, 0, DAY - 1, min_rest)
    if start < earliest:
        return (
            f"the driver would have less than {min_rest} minutes off since the previous "
            f"day's work (not before {_hhmm(earliest)})"
        )
    if end > latest:
        return (
            f"the driver would have less than {min_rest} minutes off before the next "
            f"day's work (finish by {_hhmm(latest)})"
        )
    return None
