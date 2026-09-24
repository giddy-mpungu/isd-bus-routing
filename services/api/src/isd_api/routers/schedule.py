"""spec section 21: the solver-driven schedule endpoints, plus the
human-override endpoints (PATCH/DELETE on a single assignment) that
let transportation personnel reassign a crew, adjust a time, or lock
an assignment against a future re-solve. Every manual override still
re-checks the same hard constraints the solver enforces (qualification,
capacity, no overlap, window bounds) — human override supersedes the
solver's *optimization choices*, never the safety-critical hard
constraints (README "Non-negotiables carried from spec")."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from isd_solver import (
    Crew as SolverCrew,
)
from isd_solver import (
    Driver as SolverDriver,
)
from isd_solver import (
    InfeasibleResult,
    SchedulingResult,
    SizeRestriction,
    avoid_polygons_geojson,
    ors_deadhead_estimator,
    solve_multi_school_schedule,
    straight_line_deadhead_estimator,
)
from isd_solver import (
    Job as SolverJob,
)
from isd_solver import (
    Location as SolverLocation,
)
from isd_solver import (
    TimeWindow as SolverTimeWindow,
)
from isd_solver import (
    Vehicle as SolverVehicle,
)
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.availability import (
    assignment_availability_issue,
    conflict_for_window,
    crew_availability,
)
from isd_api.config import settings
from isd_api.db import get_db
from isd_api.models import (
    Assignment,
    GeographicKnowledgeCategory,
    GeographicKnowledgeOverride,
    Role,
    User,
)
from isd_api.models import Crew as DBCrew
from isd_api.models import Run as DBRun
from isd_api.routers.announcements import _maybe_create_substitution_announcement
from isd_api.routers.optimization_settings import load_objective_weights
from isd_api.routers.runs import _resolve_riding_students
from isd_api.schemas import (
    AssignmentRead,
    AssignmentStatusUpdate,
    AssignmentStopRoster,
    AssignmentUpdate,
    DriverAssignmentRead,
    ScheduleRequest,
    ScheduleResult,
    SchoolAssignmentRead,
)
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/schedule", tags=["schedule"])

# spec section 8: which GeographicKnowledgeOverride categories become a hard,
# always-on ORS avoid-zone for the whole solve, regardless of which specific
# run/vehicle a deadhead leg is between. Deliberately NOT all 8 categories —
# OTHER is too ambiguous to apply an unpredictable effect for; PREFERRED_ENTRANCE
# is a positive preference, the opposite of an avoidance, handled entirely
# differently (see _preferred_entrance_locations: it substitutes a job's
# destination point, never touches avoid_polygons at all). CONGESTION_WINDOW
# and VEHICLE_SIZE_RESTRICTED are NOT unconditional like these four -- they're
# handled by _congestion_avoid_points and _size_restrictions_for_schedule
# below, since each needs per-solve (time) or per-vehicle context this fixed
# tuple can't express. See isd_solver.domain.ors_deadhead_estimator's
# avoid_polygons/size_restrictions docstrings for the geometry/per-call side.
#
# DIFFICULT_INTERSECTION is included here as a hard avoid -- a deliberate,
# named compromise, not a free win: the category name implies a caution/cost
# ("drive carefully here"), not a block, but ORS's directions API has no
# soft-cost lever to express that distinction. Blanket-avoiding it is a real
# behavior change from what the name implies (a route that would otherwise
# have safely used that intersection now detours around it entirely), traded
# for actually applying the knowledge at all rather than leaving it inert.
_HARD_AVOID_CATEGORIES = (
    GeographicKnowledgeCategory.FREQUENT_FLOODING,
    GeographicKnowledgeCategory.DIFFICULT_INTERSECTION,
    GeographicKnowledgeCategory.UNSAFE_TURN,
    GeographicKnowledgeCategory.INVALID_TURNAROUND,
)


def _congestion_avoid_points(db: Session, jobs: list[SolverJob]) -> list[SolverLocation]:
    """CONGESTION_WINDOW overrides are applied per-solve, not per-leg: a
    zone is included in the avoid-geometry for this whole POST /schedule
    call when ANY job actually being solved today has a required
    window overlapping the override's window_start_minute/
    window_end_minute — not only the specific deadhead legs that would
    plausibly occur during that window. This is a deliberate, named
    precision tradeoff (the same "fixed for the whole solve" shape
    _HARD_AVOID_CATEGORIES already uses) rather than threading a time
    parameter through DeadheadEstimator and every scheduler.py call
    site: a run's own required window is already known before solving
    even starts, while the exact deadhead-leg travel time is a CP-SAT
    decision variable, not known until after solving."""
    overrides = (
        db.query(GeographicKnowledgeOverride)
        .filter(
            GeographicKnowledgeOverride.category == GeographicKnowledgeCategory.CONGESTION_WINDOW
        )
        .all()
    )
    points = []
    for override in overrides:
        # window_start_minute/window_end_minute are required together at
        # creation for this exact category (routers/geographic_knowledge.py's
        # _validate_category_specific_fields) -- the DB columns are
        # nullable only because they're meaningless for every other category.
        assert override.window_start_minute is not None
        assert override.window_end_minute is not None
        overlaps_a_job_today = any(
            job.window.earliest <= override.window_end_minute
            and override.window_start_minute <= job.window.latest
            for job in jobs
        )
        if overlaps_a_job_today:
            points.append(SolverLocation(lat=override.location_lat, lon=override.location_lon))
    return points


def _size_restrictions_for_schedule(db: Session) -> tuple[SizeRestriction, ...]:
    """VEHICLE_SIZE_RESTRICTED overrides, converted to solver
    SizeRestriction objects — unlike the always-on categories above,
    these are re-evaluated by the estimator on every call against the
    specific Vehicle passed in, so no per-solve time/job filtering is
    needed here (see isd_solver.domain.ors_deadhead_estimator)."""
    overrides = (
        db.query(GeographicKnowledgeOverride)
        .filter(
            GeographicKnowledgeOverride.category
            == GeographicKnowledgeCategory.VEHICLE_SIZE_RESTRICTED
        )
        .all()
    )
    restrictions = []
    for override in overrides:
        # restricted_dimension/max_allowed_value are required together at
        # creation for this exact category (same precedent as
        # _congestion_avoid_points above) -- nullable only because they're
        # meaningless for every other category.
        assert override.restricted_dimension is not None
        assert override.max_allowed_value is not None
        restrictions.append(
            SizeRestriction(
                location=SolverLocation(lat=override.location_lat, lon=override.location_lon),
                dimension=override.restricted_dimension.value,
                max_allowed=override.max_allowed_value,
            )
        )
    return tuple(restrictions)


def _preferred_entrance_locations(db: Session) -> dict[int, SolverLocation]:
    """PREFERRED_ENTRANCE overrides, keyed by school_id — a run's job
    location is this override's own point (the entrance) instead of
    the school's own centroid, spec section 8's "use the north gate"
    example applied to the regular runs this system's solver actually
    schedules (field trips use DestinationProfile.approved_entrance
    instead, since they're never solved by CP-SAT). If more than one
    PREFERRED_ENTRANCE override exists for the same school, that
    school is left out entirely — spec section 21: don't guess which
    one applies; the run falls back to the school's own centroid."""
    overrides = (
        db.query(GeographicKnowledgeOverride)
        .filter(
            GeographicKnowledgeOverride.category == GeographicKnowledgeCategory.PREFERRED_ENTRANCE
        )
        .all()
    )
    by_school: dict[int, list[GeographicKnowledgeOverride]] = {}
    for override in overrides:
        # school_id is required at creation for this exact category
        # (same precedent as the window/threshold fields above).
        assert override.school_id is not None
        by_school.setdefault(override.school_id, []).append(override)
    return {
        school_id: SolverLocation(lat=matches[0].location_lat, lon=matches[0].location_lon)
        for school_id, matches in by_school.items()
        if len(matches) == 1
    }


def _to_solver_inputs(
    db: Session, service_date: date
) -> tuple[list[DBRun], list[DBCrew], list[SolverJob], list[SolverCrew]]:
    db_runs = db.query(DBRun).filter(DBRun.service_date == service_date).all()
    db_crews = db.query(DBCrew).filter(DBCrew.service_date == service_date).all()
    preferred_entrances = _preferred_entrance_locations(db)

    jobs = [
        SolverJob(
            id=str(r.id),
            school_id=str(r.school_id),
            window=SolverTimeWindow(earliest=r.window_earliest, latest=r.window_latest),
            duration_minutes=r.duration_minutes,
            buffer_minutes=r.buffer_minutes,
            location=preferred_entrances.get(
                r.school_id, SolverLocation(lat=r.school.location_lat, lon=r.school.location_lon)
            ),
            required_vehicle_qualifications=frozenset(q.code for q in r.required_qualifications),
            passenger_count=r.passenger_count,
        )
        for r in db_runs
    ]

    crews = [
        SolverCrew(
            id=str(c.id),
            driver=SolverDriver(
                id=str(c.driver_id),
                license_qualifications=frozenset(q.code for q in c.driver.qualifications),
                max_continuous_minutes=c.driver.max_continuous_minutes,
            ),
            vehicle=SolverVehicle(
                id=str(c.vehicle_id),
                qualifications=frozenset(q.code for q in c.vehicle.qualifications),
                nominal_capacity=c.vehicle.nominal_capacity,
                effective_capacity=c.vehicle.effective_capacity,
                length_m=c.vehicle.length_m,
                width_m=c.vehicle.width_m,
                height_m=c.vehicle.height_m,
                weight_kg=c.vehicle.weight_kg,
            ),
            available_window=SolverTimeWindow(
                earliest=c.available_window_earliest, latest=c.available_window_latest
            ),
        )
        for c in db_crews
    ]
    return db_runs, db_crews, jobs, crews


def _hard_constraint_violation(
    db: Session,
    run: DBRun,
    crew: DBCrew,
    start_minute: int,
    end_minute: int,
    *,
    exclude_assignment_id: int | None,
) -> str | None:
    """Re-checks the same hard constraints solve_multi_school_schedule
    enforces, against a single proposed (run, crew, start, end) — used
    by the manual PATCH endpoint, which doesn't go through the solver.
    Returns a human-readable violation reason, or None if valid."""
    if crew.service_date != run.service_date:
        return (
            f"Crew {crew.id} is for service_date={crew.service_date}, but "
            f"run {run.id} is for service_date={run.service_date}"
        )

    required_codes = {q.code for q in run.required_qualifications}
    crew_codes = {q.code for q in crew.vehicle.qualifications}
    if not required_codes.issubset(crew_codes):
        missing = sorted(required_codes - crew_codes)
        return f"Crew {crew.id}'s vehicle is missing required qualification(s): {missing}"

    if run.passenger_count > 0:
        capacity = crew.vehicle.allowable_capacity()
        if capacity is None or capacity < run.passenger_count:
            return (
                f"Crew {crew.id}'s vehicle capacity ({capacity}) is insufficient for "
                f"{run.passenger_count} expected passenger(s)"
            )

    if start_minute > end_minute:
        return f"start_minute ({start_minute}) must be <= end_minute ({end_minute})"
    if not (run.window_earliest <= start_minute and end_minute <= run.window_latest):
        return (
            f"[{start_minute}, {end_minute}] falls outside run {run.id}'s required "
            f"window [{run.window_earliest}, {run.window_latest}]"
        )
    if not (
        crew.available_window_earliest <= start_minute
        and end_minute <= crew.available_window_latest
    ):
        return (
            f"[{start_minute}, {end_minute}] falls outside crew {crew.id}'s available "
            f"window [{crew.available_window_earliest}, {crew.available_window_latest}]"
        )

    unavailable = conflict_for_window(db, crew, start_minute, end_minute)
    if unavailable is not None:
        return f"Crew {crew.id} is unavailable then: {unavailable}"

    others = db.query(Assignment).filter(Assignment.crew_id == crew.id)
    for other in others:
        if other.id == exclude_assignment_id:
            continue
        if start_minute < other.end_minute and other.start_minute < end_minute:
            return (
                f"Crew {crew.id} already has overlapping assignment {other.id} "
                f"({other.start_minute}-{other.end_minute})"
            )

    return None


@router.post("", response_model=ScheduleResult)
def run_schedule(
    payload: ScheduleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> ScheduleResult:
    db_runs, db_crews, jobs, crews = _to_solver_inputs(db, payload.service_date)

    if not db_runs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No runs exist for service_date={payload.service_date}",
        )
    if not db_crews:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No crews exist for service_date={payload.service_date}",
        )

    run_ids = [r.id for r in db_runs]
    existing = db.query(Assignment).filter(Assignment.run_id.in_(run_ids)).all()
    locked_assignments = [a for a in existing if a.locked]
    unlocked_assignments = [a for a in existing if not a.locked]
    locked_run_ids = {a.run_id for a in locked_assignments}

    # A locked assignment's run is already fixed (not re-optimized).
    # Its crew is NOT excluded from the re-solve — instead, the locked
    # assignment's time range becomes a busy_interval on that crew, so
    # the rest of its day stays usable for unlocked runs (spec section
    # 21: a lock protects the specific assignment, not the crew's
    # whole day). A crew with no locked assignments gets an empty
    # tuple, a no-op.
    locked_by_crew_id: dict[int, list[Assignment]] = {}
    for a in locked_assignments:
        locked_by_crew_id.setdefault(a.crew_id, []).append(a)

    unlocked_jobs = [j for j in jobs if int(j.id) not in locked_run_ids]

    # Availability (spec sections 2.1, 13): a crew whose bus is out of
    # service, whose driver is deactivated, or whose driver is absent for
    # the whole window takes no new work; a partial-day absence becomes
    # busy time alongside the locked assignments. A *locked* assignment on
    # such a crew is left in place (the lock is a human override) but is
    # flagged via AssignmentRead.availability_issue, never silently kept.
    availability = {c.id: crew_availability(db, c) for c in db_crews}
    unavailable = {
        crew_id: a.unavailable_reason
        for crew_id, a in availability.items()
        if a.unavailable_reason is not None
    }
    solvable_crews = [
        replace(
            c,
            busy_intervals=tuple(
                [
                    SolverTimeWindow(earliest=a.start_minute, latest=a.end_minute)
                    for a in locked_by_crew_id.get(int(c.id), [])
                ]
                + [
                    SolverTimeWindow(earliest=w.start_minute, latest=w.end_minute)
                    for w in availability[int(c.id)].busy_windows
                ]
            ),
        )
        for c in crews
        if int(c.id) not in unavailable
    ]

    if not unlocked_jobs:
        # Everything for this date is already locked — nothing to
        # solve; return the existing schedule unchanged, not an error.
        return ScheduleResult(
            crews_used=len({a.crew_id for a in locked_assignments}),
            assignments=[_assignment_read(db, a) for a in locked_assignments],
        )

    if not solvable_crews:
        reasons = "; ".join(f"crew {cid}: {why}" for cid, why in sorted(unavailable.items()))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"No available crews for service_date={payload.service_date} ({reasons})",
        )

    fallback_estimator = straight_line_deadhead_estimator(
        average_speed_kmh=payload.average_deadhead_speed_kmh
    )
    if settings.ors_api_key:
        avoid_points = [
            SolverLocation(lat=override.location_lat, lon=override.location_lon)
            for override in db.query(GeographicKnowledgeOverride)
            .filter(GeographicKnowledgeOverride.category.in_(_HARD_AVOID_CATEGORIES))
            .all()
        ]
        avoid_points += _congestion_avoid_points(db, unlocked_jobs)
        estimator = ors_deadhead_estimator(
            api_key=settings.ors_api_key,
            base_url=settings.ors_base_url,
            profile=settings.ors_profile,
            avoid_polygons=avoid_polygons_geojson(avoid_points),
            size_restrictions=_size_restrictions_for_schedule(db),
            fallback=fallback_estimator,
        )
    else:
        estimator = fallback_estimator
    result = solve_multi_school_schedule(
        unlocked_jobs, solvable_crews, estimator, weights=load_objective_weights(db)
    )

    if isinstance(result, InfeasibleResult):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=result.reason)

    assert isinstance(result, SchedulingResult)

    # Replace only the unlocked assignments for this date — locked ones
    # are left untouched (spec section 21: a lock must survive a
    # re-solve), audited as explicit delete+create, not a silent
    # overwrite (spec section 14).
    for old in unlocked_assignments:
        record_audit(
            db,
            entity_type="assignment",
            entity_id=old.id,
            action="deleted",
            actor=current_user,
            before_state={"run_id": old.run_id, "crew_id": old.crew_id},
        )
        db.delete(old)
    db.flush()

    created: list[Assignment] = []
    for solver_assignment in result.assignments:
        explanation = solver_assignment.explanation
        assignment = Assignment(
            run_id=int(solver_assignment.job_id),
            crew_id=int(solver_assignment.crew_id),
            start_minute=solver_assignment.start_minute,
            end_minute=solver_assignment.end_minute,
            explanation_text=explanation.text(),
            explanation_json={
                "hard_constraints_checked": list(explanation.hard_constraints_checked),
                "buffer_minutes_to_next_job": explanation.buffer_minutes_to_next_job,
                "next_job_id": explanation.next_job_id,
            },
        )
        db.add(assignment)
        db.flush()
        record_audit(
            db,
            entity_type="assignment",
            entity_id=assignment.id,
            action="created",
            actor=current_user,
            after_state={
                "run_id": assignment.run_id,
                "crew_id": assignment.crew_id,
                "start_minute": assignment.start_minute,
                "end_minute": assignment.end_minute,
            },
        )
        created.append(assignment)

    db.commit()
    for a in created:
        db.refresh(a)
    for a in locked_assignments:
        db.refresh(a)

    all_assignments = locked_assignments + created
    return ScheduleResult(
        crews_used=len({a.crew_id for a in all_assignments}),
        assignments=[_assignment_read(db, a) for a in all_assignments],
        total_deadhead_minutes=result.total_deadhead_minutes,
        total_arrival_buffer_minutes=result.total_arrival_buffer_minutes,
    )


@router.patch("/assignments/{assignment_id}", response_model=AssignmentRead)
def update_assignment(
    assignment_id: int,
    payload: AssignmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> Assignment:
    """spec section 21 human override: reassign a crew, adjust a time,
    and/or lock/unlock a single assignment. A crew/time change is
    re-validated against every hard constraint the solver enforces
    (_hard_constraint_violation) before it's written — human override
    supersedes the solver's optimization choices, never a hard
    constraint."""
    assignment = db.get(Assignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    before_state = {
        "run_id": assignment.run_id,
        "crew_id": assignment.crew_id,
        "start_minute": assignment.start_minute,
        "end_minute": assignment.end_minute,
        "locked": assignment.locked,
    }

    new_crew_id = payload.crew_id if payload.crew_id is not None else assignment.crew_id
    new_start = (
        payload.start_minute if payload.start_minute is not None else assignment.start_minute
    )
    new_end = payload.end_minute if payload.end_minute is not None else assignment.end_minute
    crew_changed = new_crew_id != assignment.crew_id
    crew: DBCrew | None = None

    if (
        new_crew_id != assignment.crew_id
        or new_start != assignment.start_minute
        or new_end != assignment.end_minute
    ):
        crew = db.get(DBCrew, new_crew_id)
        if crew is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Crew {new_crew_id} not found"
            )
        violation = _hard_constraint_violation(
            db, assignment.run, crew, new_start, new_end, exclude_assignment_id=assignment.id
        )
        if violation is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=violation)
        assignment.crew_id = new_crew_id
        assignment.start_minute = new_start
        assignment.end_minute = new_end
        # The prior explanation_text/json came from the solver and
        # names the *old* crew — leaving it in place after a manual
        # override would misattribute the decision. Replace it with
        # what was actually re-checked here (buffer/next-job context
        # isn't computed for a single manual edit — honestly reported
        # as unknown rather than reused stale from the old assignment).
        checks = [
            "vehicle/driver qualifications are satisfied",
            "it does not overlap any other job assigned to this crew",
            "it starts and ends within its required arrival window and the crew's availability",
        ]
        if assignment.run.passenger_count > 0:
            checks.append(
                "vehicle capacity is sufficient for "
                f"{assignment.run.passenger_count} expected passengers"
            )
        assignment.explanation_text = (
            f"Crew {new_crew_id} was manually assigned to job {assignment.run_id} by "
            f"{current_user.full_name} ({current_user.role.value}), overriding the "
            "previous assignment; " + "; ".join(checks) + "."
        )
        assignment.explanation_json = {
            "hard_constraints_checked": checks,
            "buffer_minutes_to_next_job": None,
            "next_job_id": None,
            "manually_overridden_by": current_user.full_name,
        }

    if payload.locked is not None:
        assignment.locked = payload.locked

    db.flush()
    record_audit(
        db,
        entity_type="assignment",
        entity_id=assignment.id,
        action="updated",
        actor=current_user,
        before_state=before_state,
        after_state={
            "run_id": assignment.run_id,
            "crew_id": assignment.crew_id,
            "start_minute": assignment.start_minute,
            "end_minute": assignment.end_minute,
            "locked": assignment.locked,
        },
    )
    if crew_changed:
        assert crew is not None  # crew_changed implies the block above set it
        _maybe_create_substitution_announcement(db, crew, current_user)
    db.commit()
    db.refresh(assignment)
    return assignment


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> None:
    """spec section 21 human override: remove a single assignment
    (e.g. cancel a run's crew assignment) without a full re-solve."""
    assignment = db.get(Assignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")

    record_audit(
        db,
        entity_type="assignment",
        entity_id=assignment.id,
        action="deleted",
        actor=current_user,
        before_state={
            "run_id": assignment.run_id,
            "crew_id": assignment.crew_id,
            "start_minute": assignment.start_minute,
            "end_minute": assignment.end_minute,
            "locked": assignment.locked,
        },
    )
    db.delete(assignment)
    db.commit()


@router.get("/{service_date}/assignments", response_model=list[AssignmentRead])
def list_assignments(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AssignmentRead]:
    """spec section 17 access scoping: admin/dispatcher see everything;
    school_admin sees only assignments for runs at their school; driver
    sees only assignments for their own crew; student/parent have no
    access here (deferred — no Student/Guardian model yet)."""
    query = (
        db.query(Assignment)
        .join(DBRun, Assignment.run_id == DBRun.id)
        .filter(DBRun.service_date == service_date)
    )

    if current_user.role in (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER):
        pass
    elif current_user.role == Role.SCHOOL_ADMIN:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This school_admin account is not linked to a school",
            )
        query = query.filter(DBRun.school_id == current_user.school_id)
    elif current_user.role == Role.DRIVER:
        if current_user.driver_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This driver account is not linked to a Driver record",
            )
        query = query.join(DBCrew, Assignment.crew_id == DBCrew.id).filter(
            DBCrew.driver_id == current_user.driver_id
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role.value}' cannot list assignments directly",
        )

    return [_assignment_read(db, a) for a in query.order_by(Assignment.id).all()]


def _assignment_read(db: Session, assignment: Assignment) -> AssignmentRead:
    read = AssignmentRead.model_validate(assignment)
    read.availability_issue = assignment_availability_issue(db, assignment)
    return read


def _stop_roster_for(db: Session, run: DBRun) -> tuple[bool, list[AssignmentStopRoster]]:
    """Shared by list_my_assignments and update_assignment_status so a
    driver's roster looks the same whether they just loaded their day
    or just updated a status. Grouped by stop, not sequenced/ordered —
    see AssignmentStopRoster's own docstring for why. Empty when
    ambiguous (spec section 21: don't guess)."""
    riding_students, ambiguous = _resolve_riding_students(db, run)
    if ambiguous:
        return True, []
    by_stop: dict[str | None, list[str]] = {}
    for s in riding_students:
        label = s.stop.label if s.stop is not None else None
        by_stop.setdefault(label, []).append(s.full_name)
    stops = [
        AssignmentStopRoster(stop_label=label, student_names=sorted(names))
        for label, names in sorted(by_stop.items(), key=lambda kv: (kv[0] is None, kv[0]))
    ]
    return False, stops


@router.get("/{service_date}/my-assignments", response_model=list[DriverAssignmentRead])
def list_my_assignments(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.DRIVER)),
) -> list[DriverAssignmentRead]:
    """Phase 4: a driver's own runs for a date, with school/vehicle
    names resolved server-side — a driver has no other endpoint that
    can resolve those (GET /runs, /crews, /drivers are all
    admin/dispatcher-only, ADR 0006 least-privilege), so this is a
    purpose-built, denormalized read rather than broadening those."""
    if current_user.driver_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This driver account is not linked to a Driver record",
        )
    assignments = (
        db.query(Assignment)
        .join(DBRun, Assignment.run_id == DBRun.id)
        .join(DBCrew, Assignment.crew_id == DBCrew.id)
        .filter(DBRun.service_date == service_date, DBCrew.driver_id == current_user.driver_id)
        .order_by(Assignment.start_minute)
        .all()
    )
    results = []
    for a in assignments:
        ambiguous, stops = _stop_roster_for(db, a.run)
        results.append(
            DriverAssignmentRead(
                id=a.id,
                run_id=a.run_id,
                service_date=a.run.service_date,
                school_name=a.run.school.name,
                vehicle_label=a.crew.vehicle.label,
                start_minute=a.start_minute,
                end_minute=a.end_minute,
                status=a.status,
                locked=a.locked,
                roster_ambiguous=ambiguous,
                stops=stops,
            )
        )
    return results


@router.get("/{service_date}/school-assignments", response_model=list[SchoolAssignmentRead])
def list_school_assignments(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.SCHOOL_ADMIN)),
) -> list[SchoolAssignmentRead]:
    """spec section 17: School Administrator sees "buses serving the
    school" and "expected arrivals" for their own school — resolved
    driver/vehicle names server-side, the same least-privilege reason
    DriverAssignmentRead exists (school_admin has no other endpoint
    that can resolve GET /drivers or /crews). "Delayed buses" from that
    same access list isn't surfaced here — there's no ETA-calculation
    engine anywhere in this system (spec §18's own gap), so there's
    nothing honest to compute a delay against yet."""
    if current_user.school_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This school_admin account is not linked to a school",
        )
    assignments = (
        db.query(Assignment)
        .join(DBRun, Assignment.run_id == DBRun.id)
        .join(DBCrew, Assignment.crew_id == DBCrew.id)
        .filter(DBRun.service_date == service_date, DBRun.school_id == current_user.school_id)
        .order_by(Assignment.start_minute)
        .all()
    )
    return [
        SchoolAssignmentRead(
            id=a.id,
            run_id=a.run_id,
            service_date=a.run.service_date,
            direction=a.run.direction,
            window_earliest=a.run.window_earliest,
            window_latest=a.run.window_latest,
            driver_full_name=a.crew.driver.full_name,
            vehicle_label=a.crew.vehicle.label,
            start_minute=a.start_minute,
            end_minute=a.end_minute,
            status=a.status,
            locked=a.locked,
        )
        for a in assignments
    ]


@router.patch("/assignments/{assignment_id}/status", response_model=DriverAssignmentRead)
def update_assignment_status(
    assignment_id: int,
    payload: AssignmentStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.DRIVER)),
) -> DriverAssignmentRead:
    """Phase 4: a driver reports progress on their own run (started /
    completed / no-show). Distinct from PATCH /assignments/{id}, which
    is the dispatcher-only scheduling override — a status change never
    touches crew/time/lock and needs no hard-constraint re-check."""
    assignment = db.get(Assignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    if assignment.crew.driver_id != current_user.driver_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own assignments",
        )

    before_status = assignment.status
    assignment.status = payload.status
    assignment.status_updated_at = datetime.now(UTC)
    db.flush()
    record_audit(
        db,
        entity_type="assignment",
        entity_id=assignment.id,
        action="status_changed",
        actor=current_user,
        before_state={"status": before_status.value},
        after_state={"status": assignment.status.value},
    )
    db.commit()
    db.refresh(assignment)
    ambiguous, stops = _stop_roster_for(db, assignment.run)
    return DriverAssignmentRead(
        id=assignment.id,
        run_id=assignment.run_id,
        service_date=assignment.run.service_date,
        school_name=assignment.run.school.name,
        vehicle_label=assignment.crew.vehicle.label,
        start_minute=assignment.start_minute,
        end_minute=assignment.end_minute,
        status=assignment.status,
        locked=assignment.locked,
        roster_ambiguous=ambiguous,
        stops=stops,
    )
