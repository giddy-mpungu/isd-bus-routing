"""Which run a student rides, and who rides a run (spec sections 3, 4, 9).

A student belongs to a school; each school day has one or more runs per
leg (AM or PM). Which of several runs a student rides is decided by their
stop: the run whose recurring route (`RouteTemplate.stops`) includes it.

  - One run on the leg: every riding student of the school is on it.
  - Several runs: a student is on the run whose route includes their
    stop. With no stop, a stop on no route, or a stop on more than one of
    the leg's routes, they can't be placed (spec section 21: don't guess).
  - A run with no route stops, on a leg with other runs, can't claim
    anyone, so its rider list stays ambiguous (the behaviour before routes
    existed).

Riding means the student's default ridership, or that day's override.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from isd_api.models import RideDirection, RidershipOverride, RouteStop, Run, Student, Vehicle


def leg_runs(
    db: Session, school_id: int, service_date: date, direction: RideDirection
) -> list[Run]:
    return (
        db.query(Run)
        .filter(
            Run.school_id == school_id,
            Run.service_date == service_date,
            Run.direction == direction,
        )
        .order_by(Run.id)
        .all()
    )


def route_stop_ids(db: Session, run: Run) -> set[int]:
    if run.route_template_id is None:
        return set()
    return {
        stop_id
        for (stop_id,) in db.query(RouteStop.stop_id).filter(
            RouteStop.route_template_id == run.route_template_id
        )
    }


def run_for_student(
    db: Session, student: Student, service_date: date, direction: RideDirection
) -> tuple[Run | None, bool]:
    """(the run this student rides, whether that's ambiguous)."""
    runs = leg_runs(db, student.school_id, service_date, direction)
    if not runs:
        return None, False
    if len(runs) == 1:
        return runs[0], False
    if student.stop_id is None:
        return None, True
    serving = [r for r in runs if student.stop_id in route_stop_ids(db, r)]
    if len(serving) == 1:
        return serving[0], False
    return None, True


def _riding(db: Session, students: list[Student], run: Run) -> list[Student]:
    overrides = {
        o.student_id: o.is_riding
        for o in db.query(RidershipOverride).filter(
            RidershipOverride.student_id.in_([s.id for s in students]),
            RidershipOverride.service_date == run.service_date,
            RidershipOverride.direction == run.direction,
        )
    }
    return [
        s
        for s in students
        if (s.withdrawn_on is None or s.withdrawn_on > run.service_date)
        and overrides.get(s.id, s.default_ridership.value == "rides")
    ]


def expected_demand(db: Session, run: Run) -> int:
    """How many passengers the run's bus must have room for (spec section
    15): the count entered on the run, or that day's riders when there are
    more and they can be pinned to this run. Never less than what was
    entered, since a dispatcher may plan for more; when the riders can't be
    attributed to one run (several on the leg without stop lists), only the
    entered count is known."""
    riders, ambiguous = riders_for_run(db, run)
    return run.passenger_count if ambiguous else max(run.passenger_count, len(riders))


def wheelchair_demand(db: Session, run: Run) -> int:
    """That day's riders pinned to the run who ride in their wheelchair (an
    accommodation that takes a wheelchair position, spec section 6); 0
    when the riders can't be attributed to one run."""
    riders, ambiguous = riders_for_run(db, run)
    if ambiguous:
        return 0
    return sum(1 for s in riders if any(q.takes_wheelchair_position for q in s.accommodations))


def seat_problem(db: Session, run: Run, vehicle: Vehicle) -> str | None:
    """Why `vehicle` can't carry the run's riders (seats, then wheelchair
    positions; unknown counts fail closed), or None."""
    demand = expected_demand(db, run)
    seats = vehicle.allowable_capacity()
    if demand > 0 and (seats is None or seats < demand):
        return (
            f"{vehicle.label} has {'an unknown number of' if seats is None else seats} "
            f"seats for {demand} expected riders"
        )
    chairs = wheelchair_demand(db, run)
    positions = vehicle.wheelchair_positions
    if chairs > 0 and (positions is None or positions < chairs):
        return (
            f"{vehicle.label} has {'no recorded' if positions is None else positions} "
            f"wheelchair position{'' if positions == 1 else 's'} for {chairs} "
            f"rider{'' if chairs == 1 else 's'} in a wheelchair"
        )
    return None


def riders_for_run(db: Session, run: Run) -> tuple[list[Student], bool]:
    """(riding students on this run, whether the list is ambiguous).
    Callers must not use the list when it's ambiguous."""
    runs = leg_runs(db, run.school_id, run.service_date, run.direction)
    students = db.query(Student).filter(Student.school_id == run.school_id).all()
    if len(runs) <= 1:
        return _riding(db, students, run), False
    mine = route_stop_ids(db, run)
    if not mine:
        return [], True
    others = set().union(*(route_stop_ids(db, r) for r in runs if r.id != run.id))
    # A stop on this route and no other of the leg's routes.
    placed = [s for s in students if s.stop_id in mine and s.stop_id not in others]
    return _riding(db, placed, run), False


def route_lock_problem(db: Session, route_template_id: int) -> str | None:
    """Spec section 4.4's route lock: why this route's stops can't change
    now (a run of it today leaves within the district's lock, or is under
    way), or None. Changes are fine again once that run is done."""
    from isd_api.assignment_states import TERMINAL
    from isd_api.ridership_rules import district_now, hhmm, load_rules

    rules = load_rules(db)
    if not rules.route_lock_minutes:
        return None
    local = district_now(rules)
    now = local.hour * 60 + local.minute
    for run in db.query(Run).filter(
        Run.route_template_id == route_template_id, Run.service_date == local.date()
    ):
        assignment = run.assignment
        if assignment is None or assignment.status in TERMINAL:
            continue
        if assignment.start_minute - now <= rules.route_lock_minutes:
            return (
                f"Today's {run.school.name} {run.direction.value.upper()} run leaves at "
                f"{hhmm(assignment.start_minute)}, so its stops are locked from "
                f"{hhmm(max(0, assignment.start_minute - rules.route_lock_minutes))} "
                f"(the district's {rules.route_lock_minutes}-minute route lock). "
                "Change them once it's done."
            )
    return None
