from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import (
    Assignment,
    AssignmentStatus,
    AuditLogEntry,
    RideDirection,
    RidershipOverride,
    Role,
    Run,
    School,
    Student,
    User,
)
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.schemas import (
    ExpectedRidersRead,
    ObservedRunDurationRead,
    RunCreate,
    RunRead,
    RunUpdate,
)
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/runs", tags=["runs"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


@router.post("", response_model=RunRead, status_code=status.HTTP_201_CREATED)
def create_run(
    payload: RunCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> Run:
    if payload.window_earliest > payload.window_latest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="window_earliest must be <= window_latest",
        )
    if payload.duration_minutes + payload.buffer_minutes > (
        payload.window_latest - payload.window_earliest
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duration_minutes + buffer_minutes exceeds the run's own window length",
        )
    if db.get(School, payload.school_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")

    run = Run(
        service_date=payload.service_date,
        school_id=payload.school_id,
        direction=payload.direction,
        window_earliest=payload.window_earliest,
        window_latest=payload.window_latest,
        duration_minutes=payload.duration_minutes,
        buffer_minutes=payload.buffer_minutes,
        passenger_count=payload.passenger_count,
        required_qualifications=_resolve_qualifications(db, payload.required_qualification_codes),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.get("", response_model=list[RunRead])
def list_runs(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Run]:
    """spec section 17: School Administrator sees buses/runs serving
    their school; Dispatcher/Transportation Administrator see everything.
    Driver/Student/Parent have no direct run-listing access here — a
    driver's own upcoming work comes from /schedule/{date}/assignments,
    scoped to their crew.
    """
    query = db.query(Run).filter(Run.service_date == service_date)
    if current_user.role == Role.SCHOOL_ADMIN:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This school_admin account is not linked to a school",
            )
        query = query.filter(Run.school_id == current_user.school_id)
    elif current_user.role not in (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role.value}' cannot list runs directly",
        )
    return list(query.order_by(Run.id).all())


@router.get("/observed-duration", response_model=ObservedRunDurationRead)
def get_observed_run_duration(
    school_id: int,
    direction: RideDirection,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> ObservedRunDurationRead:
    """spec section 20: "if a route consistently requires 48 minutes
    despite an initial estimate of 40 minutes, future schedules should
    be capable of adjusting toward the observed operational duration."
    Computed entirely from data this system already persists -- no new
    breadcrumb/history table. Runs have no recurring-route identity
    (ADR 0001's never-built Route/template table), so "this route" is
    approximated as every completed Assignment for a Run sharing this
    (school_id, direction) across any service_date. A completed
    assignment's actual start/end aren't new columns either -- they're
    read straight off its own status_changed audit entries (spec
    section 14): the timestamp the audit log recorded when a driver's
    PATCH .../status flipped it to in_progress, and again to completed.
    Decision support only (spec section 21) -- a dispatcher reads this
    and manually sets duration_minutes on a new run; nothing here
    writes to Run.duration_minutes automatically."""
    assignments = (
        db.query(Assignment)
        .join(Run, Assignment.run_id == Run.id)
        .filter(
            Run.school_id == school_id,
            Run.direction == direction,
            Assignment.status == AssignmentStatus.COMPLETED,
        )
        .all()
    )

    samples: list[tuple[date, float]] = []
    for assignment in assignments:
        entries = (
            db.query(AuditLogEntry)
            .filter(
                AuditLogEntry.entity_type == "assignment",
                AuditLogEntry.entity_id == assignment.id,
                AuditLogEntry.action == "status_changed",
            )
            .order_by(AuditLogEntry.created_at)
            .all()
        )
        started_at = next(
            (e.created_at for e in entries if (e.after_state or {}).get("status") == "in_progress"),
            None,
        )
        completed_at = next(
            (e.created_at for e in entries if (e.after_state or {}).get("status") == "completed"),
            None,
        )
        if started_at is not None and completed_at is not None and completed_at > started_at:
            samples.append(
                (assignment.run.service_date, (completed_at - started_at).total_seconds() / 60)
            )

    if not samples:
        return ObservedRunDurationRead(
            sample_count=0,
            average_actual_minutes=None,
            most_recent_actual_minutes=None,
            most_recent_service_date=None,
        )

    samples.sort(key=lambda s: s[0])
    average = sum(minutes for _, minutes in samples) / len(samples)
    most_recent_date, most_recent_minutes = samples[-1]
    return ObservedRunDurationRead(
        sample_count=len(samples),
        average_actual_minutes=round(average, 1),
        most_recent_actual_minutes=round(most_recent_minutes),
        most_recent_service_date=most_recent_date,
    )


@router.patch("/{run_id}", response_model=RunRead)
def update_run(
    run_id: int,
    payload: RunUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> Run:
    """Deliberately minimal — only passenger_count, the one field the
    expected-riders decision-support flow (below) needs to let a
    dispatcher apply a computed count. Not a general run-editing
    endpoint; window/duration/school changes aren't supported here."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    before_state = {"passenger_count": run.passenger_count}
    if payload.passenger_count is not None:
        run.passenger_count = payload.passenger_count
    db.flush()
    record_audit(
        db,
        entity_type="run",
        entity_id=run.id,
        action="updated",
        actor=current_user,
        before_state=before_state,
        after_state={"passenger_count": run.passenger_count},
    )
    db.commit()
    db.refresh(run)
    return run


@router.get("/{run_id}/expected-riders", response_model=ExpectedRidersRead)
def get_expected_riders(
    run_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> ExpectedRidersRead:
    """Decision support (spec section 21: never autonomous) for setting
    Run.passenger_count from real Student/RidershipOverride data,
    instead of the fully manual guess it is today. Mirrors
    routers/students.py's get_my_family override-with-default-fallback
    resolution exactly. ambiguous=True when more than one Run exists
    for this run's (school_id, service_date, direction) — this system
    has no student-to-specific-run assignment, so a count can't be
    correctly attributed to just one of several runs serving the same
    school/leg that day; the caller should not apply the count in that
    case (routers/runs.py's PATCH doesn't enforce this itself — the
    frontend disables "Apply" when ambiguous, same as every other
    decision-support-not-autonomous-authority flow in this project)."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    other_runs_same_leg = (
        db.query(Run)
        .filter(
            Run.school_id == run.school_id,
            Run.service_date == run.service_date,
            Run.direction == run.direction,
            Run.id != run.id,
        )
        .count()
    )

    students = db.query(Student).filter(Student.school_id == run.school_id).all()
    overrides = {
        o.student_id: o.is_riding
        for o in db.query(RidershipOverride)
        .filter(
            RidershipOverride.student_id.in_([s.id for s in students]),
            RidershipOverride.service_date == run.service_date,
            RidershipOverride.direction == run.direction,
        )
        .all()
    }
    riding_students = [
        s for s in students if overrides.get(s.id, s.default_ridership.value == "rides")
    ]
    return ExpectedRidersRead(
        expected_passenger_count=len(riding_students),
        ambiguous=other_runs_same_leg > 0,
        riding_student_names=[s.full_name for s in riding_students],
    )
