"""Bridges the persisted domain (schools/runs/crews) to isd_solver and
back. This is Phase 2's proof point: the Phase 1 solver, running
behind an authenticated, RBAC-checked, audited HTTP endpoint against
real persisted data — not a standalone script anymore.
"""

from __future__ import annotations

from datetime import date

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
from isd_api.db import get_db
from isd_api.models import Assignment, Role, User
from isd_api.models import Crew as DBCrew
from isd_api.models import Run as DBRun
from isd_api.schemas import AssignmentRead, ScheduleRequest, ScheduleResult
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _to_solver_inputs(
    db: Session, service_date: date
) -> tuple[list[DBRun], list[DBCrew], list[SolverJob], list[SolverCrew]]:
    db_runs = db.query(DBRun).filter(DBRun.service_date == service_date).all()
    db_crews = db.query(DBCrew).filter(DBCrew.service_date == service_date).all()

    jobs = [
        SolverJob(
            id=str(r.id),
            school_id=str(r.school_id),
            window=SolverTimeWindow(earliest=r.window_earliest, latest=r.window_latest),
            duration_minutes=r.duration_minutes,
            buffer_minutes=r.buffer_minutes,
            location=SolverLocation(lat=r.school.location_lat, lon=r.school.location_lon),
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
            ),
            available_window=SolverTimeWindow(
                earliest=c.available_window_earliest, latest=c.available_window_latest
            ),
        )
        for c in db_crews
    ]
    return db_runs, db_crews, jobs, crews


@router.post("", response_model=ScheduleResult)
def run_schedule(
    payload: ScheduleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> ScheduleResult:
    db_runs, _db_crews, jobs, crews = _to_solver_inputs(db, payload.service_date)

    if not jobs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No runs exist for service_date={payload.service_date}",
        )
    if not crews:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No crews exist for service_date={payload.service_date}",
        )

    estimator = straight_line_deadhead_estimator(
        average_speed_kmh=payload.average_deadhead_speed_kmh
    )
    result = solve_multi_school_schedule(jobs, crews, estimator)

    if isinstance(result, InfeasibleResult):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=result.reason)

    assert isinstance(result, SchedulingResult)

    # Re-running schedule for a date replaces any prior assignments for
    # that date's runs — audited as explicit delete+create, not a
    # silent overwrite (spec section 14).
    run_ids = [r.id for r in db_runs]
    existing = db.query(Assignment).filter(Assignment.run_id.in_(run_ids)).all()
    for old in existing:
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

    return ScheduleResult(
        crews_used=result.crews_used,
        assignments=[AssignmentRead.model_validate(a) for a in created],
    )


@router.get("/{service_date}/assignments", response_model=list[AssignmentRead])
def list_assignments(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Assignment]:
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

    return list(query.order_by(Assignment.id).all())
