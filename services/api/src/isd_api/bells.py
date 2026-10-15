"""School bell schedules (spec sections 1, 5, 19) and the bus windows they set.

Decided by the product owner on 2026-10-15:
- Each school has a Regular bell schedule and may have named alternates
  (Early release, Late start, ...); a calendar marks the dates that use
  an alternate.
- A bus's window comes from the bells: the district sets how long before
  the first bell a morning bus arrives and how long after dismissal an
  afternoon bus leaves; a school may set its own. A recurring route
  follows the bells unless staff turn that off for it.
- When bells change, runs already generated for days still to come get
  the new window if they haven't started; dispatch sees an alert for any
  whose assigned times no longer fit (isd_api/alerts.py) and decides
  whether to run the schedule again. Nothing re-solves on its own (spec
  section 21).
- Transportation administrators maintain bells (and can import them from
  a CSV); school administrators see their own school's.

A run's window is the whole span it must start and finish in (the solver
holds a run inside its window). So for a morning run arriving between
`arrive_earliest_before` and `arrive_latest_before` minutes before the
first bell, the window ends at the latest arrival and starts at the
earliest arrival less the run's own duration and buffer: wherever the
solver places the run, it reaches the school in that range. An afternoon
run leaves between `leave_earliest_after` and `leave_latest_after`
minutes after dismissal, so its window starts at the earliest departure
and ends at the latest departure plus its duration and buffer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from isd_api import ridership_rules
from isd_api.audit import record as record_audit
from isd_api.models import (
    Assignment,
    AssignmentStatus,
    BellCalendarDay,
    BellRules,
    BellSchedule,
    RideDirection,
    RouteTemplate,
    Run,
    School,
    User,
)

DEFAULT_ARRIVE_EARLIEST_BEFORE = 25
DEFAULT_ARRIVE_LATEST_BEFORE = 10
DEFAULT_LEAVE_EARLIEST_AFTER = 5
DEFAULT_LEAVE_LATEST_AFTER = 15
_RULES_ID = 1
_LAST_MINUTE = 24 * 60 - 1
# A run in one of these hasn't started, so its window can still move.
NOT_STARTED = {AssignmentStatus.SENT, AssignmentStatus.RECEIVED, AssignmentStatus.ACKNOWLEDGED}


@dataclass(frozen=True)
class Offsets:
    arrive_earliest_before: int
    arrive_latest_before: int
    leave_earliest_after: int
    leave_latest_after: int


def district_offsets(db: Session) -> tuple[Offsets, bool]:
    """The district's windows, and whether they're still the defaults."""
    row = db.get(BellRules, _RULES_ID)
    if row is None:
        return (
            Offsets(
                DEFAULT_ARRIVE_EARLIEST_BEFORE,
                DEFAULT_ARRIVE_LATEST_BEFORE,
                DEFAULT_LEAVE_EARLIEST_AFTER,
                DEFAULT_LEAVE_LATEST_AFTER,
            ),
            True,
        )
    return (
        Offsets(
            row.arrive_earliest_before,
            row.arrive_latest_before,
            row.leave_earliest_after,
            row.leave_latest_after,
        ),
        False,
    )


def save_district_offsets(db: Session, offsets: Offsets) -> None:
    row = db.get(BellRules, _RULES_ID)
    if row is None:
        row = BellRules(id=_RULES_ID)
        db.add(row)
    row.arrive_earliest_before = offsets.arrive_earliest_before
    row.arrive_latest_before = offsets.arrive_latest_before
    row.leave_earliest_after = offsets.leave_earliest_after
    row.leave_latest_after = offsets.leave_latest_after


def school_has_own_offsets(school: School) -> bool:
    return school.arrive_earliest_before is not None


def offsets_for(db: Session, school: School) -> Offsets:
    """The school's own windows if it has them, else the district's."""
    if school_has_own_offsets(school):
        assert school.arrive_latest_before is not None
        assert school.leave_earliest_after is not None
        assert school.leave_latest_after is not None
        return Offsets(
            school.arrive_earliest_before,  # type: ignore[arg-type]
            school.arrive_latest_before,
            school.leave_earliest_after,
            school.leave_latest_after,
        )
    return district_offsets(db)[0]


def offsets_problem(offsets: Offsets) -> str | None:
    """Why these windows can't be used, or None."""
    values = (
        offsets.arrive_earliest_before,
        offsets.arrive_latest_before,
        offsets.leave_earliest_after,
        offsets.leave_latest_after,
    )
    if any(v < 0 or v > 180 for v in values):
        return "Each number of minutes must be between 0 and 180"
    if offsets.arrive_earliest_before < offsets.arrive_latest_before:
        return "The earliest arrival must be at least as long before the bell as the latest"
    if offsets.leave_earliest_after > offsets.leave_latest_after:
        return "The earliest departure must come before the latest"
    return None


def regular_schedule(school: School) -> BellSchedule | None:
    return next((s for s in school.bell_schedules if s.is_regular), None)


def schedule_on(db: Session, school: School, service_date: date) -> BellSchedule | None:
    """The bells a school keeps on a date: the calendar's choice, else its
    regular schedule, else None (no bells set)."""
    day = (
        db.query(BellCalendarDay)
        .filter(
            BellCalendarDay.school_id == school.id,
            BellCalendarDay.service_date == service_date,
        )
        .one_or_none()
    )
    if day is not None:
        return day.schedule
    return regular_schedule(school)


def window(
    schedule: BellSchedule,
    offsets: Offsets,
    direction: RideDirection,
    duration_minutes: int,
    buffer_minutes: int,
) -> tuple[int, int]:
    """The (earliest, latest) window a run must start and finish in."""
    occupied = duration_minutes + buffer_minutes
    if direction == RideDirection.AM:
        latest = schedule.first_bell_minute - offsets.arrive_latest_before
        earliest = schedule.first_bell_minute - offsets.arrive_earliest_before - occupied
    else:
        earliest = schedule.dismissal_minute + offsets.leave_earliest_after
        latest = schedule.dismissal_minute + offsets.leave_latest_after + occupied
    return max(0, earliest), min(_LAST_MINUTE, latest)


def template_window(
    db: Session, template: RouteTemplate, service_date: date | None = None
) -> tuple[int, int] | None:
    """A route's window from its school's bells on a date (the regular
    day if no date), or None when it doesn't follow bells or the school
    has none for that day."""
    if not template.follows_bells:
        return None
    school = template.school
    schedule = (
        regular_schedule(school) if service_date is None else schedule_on(db, school, service_date)
    )
    if schedule is None:
        return None
    return window(
        schedule,
        offsets_for(db, school),
        template.direction,
        template.duration_minutes,
        template.buffer_minutes,
    )


def district_today(db: Session) -> date:
    return ridership_rules.district_now(ridership_rules.load_rules(db)).date()


@dataclass(frozen=True)
class Moved:
    run_id: int
    service_date: date
    before: tuple[int, int]
    after: tuple[int, int]
    assigned: bool


def refresh_windows(db: Session, school_ids: set[int] | None = None) -> list[Moved]:
    """Bring bell-following routes and their runs for today and later up to
    date with the bells (after a change to bells, the calendar or the
    windows). A run already under way, or finished, keeps its window.
    Returns the runs whose window moved; the caller audits and commits."""
    query = db.query(RouteTemplate).filter(RouteTemplate.follows_bells.is_(True))
    if school_ids is not None:
        query = query.filter(RouteTemplate.school_id.in_(school_ids))
    templates = query.all()
    for template in templates:
        regular = template_window(db, template)
        if regular is not None:
            template.window_earliest, template.window_latest = regular

    if not templates:
        return []
    template_ids = [t.id for t in templates]
    moved: list[Moved] = []
    runs = (
        db.query(Run)
        .filter(
            Run.route_template_id.in_(template_ids),
            Run.service_date >= district_today(db),
        )
        .all()
    )
    for run in runs:
        assignment = db.query(Assignment).filter(Assignment.run_id == run.id).one_or_none()
        if assignment is not None and assignment.status not in NOT_STARTED:
            continue
        schedule = schedule_on(db, run.school, run.service_date)
        if schedule is None:
            continue
        # The run's own duration: route planning may have changed the route's since.
        new = window(
            schedule,
            offsets_for(db, run.school),
            run.direction,
            run.duration_minutes,
            run.buffer_minutes,
        )
        if new == (run.window_earliest, run.window_latest):
            continue
        moved.append(
            Moved(
                run.id,
                run.service_date,
                (run.window_earliest, run.window_latest),
                new,
                assignment is not None,
            )
        )
        run.window_earliest, run.window_latest = new
    return moved


def audit_moved_runs(db: Session, moved: list[Moved], actor: User) -> None:
    for m in moved:
        record_audit(
            db,
            entity_type="run",
            entity_id=m.run_id,
            action="window_from_bells",
            actor=actor,
            before_state={"window": list(m.before)},
            after_state={"window": list(m.after), "assigned": m.assigned},
        )
