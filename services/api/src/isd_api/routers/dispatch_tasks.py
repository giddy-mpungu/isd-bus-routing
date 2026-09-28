"""Spec sections 11 and 14: dispatch tasks, the unplanned work a dispatcher
sends to a driver's tablet (cover another route, assist a disabled bus,
pick up transferred passengers, return to a school, move a vehicle,
assist another driver, respond to an emergency).

- A task follows the same lifecycle as a regular assignment
  (`isd_api/assignment_states.py`): drivers move it forward from the
  tablet, dispatch can set any state, and handing an unstarted task to
  another driver sends it again.
- It's busy time for its driver and vehicle (`isd_api/availability.py`),
  so the solver, manual reassignment, field trips and substitute ranking
  all see it.
- **Conflicts** mirror field trips (section 12.1). A deactivated, absent
  or unlicensed driver, an out-of-service bus, or an overlapping field
  trip or other task refuses the task (409). A clash with a regular route
  doesn't: an emergency may well take priority. That route is flagged
  "needs cover" on the schedule, and the task lists it in
  `routes_needing_cover`.
- Cancelling keeps the row and its audit trail and frees the time. The
  driver's tablet still shows it, marked cancelled, so the driver isn't
  left wondering where it went.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from isd_api.assignment_states import driver_transition_problem, resets_on_new_driver
from isd_api.audit import record as record_audit
from isd_api.availability import (
    driver_absences,
    task_label,
    tasks_blocking,
    trips_blocking,
)
from isd_api.db import get_db
from isd_api.licensing import license_violation
from isd_api.models import (
    Assignment,
    AssignmentStatus,
    Crew,
    DispatchTask,
    Driver,
    Role,
    User,
    Vehicle,
)
from isd_api.schemas import (
    AssignmentStatusUpdate,
    DispatchTaskCreate,
    DispatchTaskRead,
    DispatchTaskUpdate,
    DriverDispatchTaskRead,
)
from isd_api.security import require_role

router = APIRouter(prefix="/dispatch-tasks", tags=["dispatch-tasks"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _conflicts(
    db: Session,
    *,
    service_date: date,
    start_minute: int,
    end_minute: int,
    driver: Driver,
    vehicle: Vehicle | None,
    exclude_task_id: int | None = None,
) -> tuple[list[str], list[str]]:
    """(blocking, routes_needing_cover) for a prospective task."""
    blocking: list[str] = []
    if not driver.is_active:
        blocking.append(f"Driver {driver.full_name} is deactivated")
    if vehicle is not None:
        if not vehicle.is_active:
            blocking.append(f"Vehicle {vehicle.label} is out of service")
        unlicensed = license_violation(driver, vehicle)
        if unlicensed is not None:
            blocking.append(unlicensed[0].upper() + unlicensed[1:])

    def overlaps(start: int, end: int) -> bool:
        return start_minute < end and start < end_minute

    for absence in driver_absences(db, driver.id, service_date):
        if overlaps(absence.start_minute, absence.end_minute):
            blocking.append(
                f"Driver {driver.full_name} is absent "
                f"({absence.reason.value.replace('_', ' ')}, "
                f"{_hhmm(absence.start_minute)}-{_hhmm(absence.end_minute)})"
            )
    vehicle_id = vehicle.id if vehicle is not None else None
    for trip, start, end in trips_blocking(
        db, service_date, driver_id=driver.id, vehicle_id=vehicle_id
    ):
        if overlaps(start, end):
            blocking.append(
                f"Field trip #{trip.id} to {trip.destination} "
                f"(held {_hhmm(start)}-{_hhmm(end)}) overlaps this task"
            )
    for other in tasks_blocking(
        db,
        service_date,
        driver_id=driver.id,
        vehicle_id=vehicle_id,
        exclude_task_id=exclude_task_id,
    ):
        if overlaps(other.start_minute, other.end_minute):
            blocking.append(f"Already {task_label(other)}")

    return blocking, _routes_needing_cover(
        db, service_date, start_minute, end_minute, driver.id, vehicle_id
    )


def _routes_needing_cover(
    db: Session,
    service_date: date,
    start_minute: int,
    end_minute: int,
    driver_id: int,
    vehicle_id: int | None,
) -> list[str]:
    resources = [Crew.driver_id == driver_id]
    if vehicle_id is not None:
        resources.append(Crew.vehicle_id == vehicle_id)
    assignments = (
        db.query(Assignment)
        .join(Crew, Assignment.crew_id == Crew.id)
        .filter(
            Crew.service_date == service_date,
            or_(*resources),
            Assignment.start_minute < end_minute,
            Assignment.end_minute > start_minute,
        )
        .order_by(Assignment.start_minute)
        .all()
    )
    return [
        f"{a.run.school.name} {a.run.direction.value.upper()} run on {a.crew.vehicle.label} "
        f"({_hhmm(a.start_minute)}-{_hhmm(a.end_minute)})"
        for a in assignments
    ]


def _read(db: Session, task: DispatchTask) -> DispatchTaskRead:
    cancelled = task.cancelled_at is not None
    return DispatchTaskRead(
        id=task.id,
        kind=task.kind,
        service_date=task.service_date,
        start_minute=task.start_minute,
        end_minute=task.end_minute,
        driver_id=task.driver_id,
        driver_full_name=task.driver.full_name,
        vehicle_id=task.vehicle_id,
        vehicle_label=task.vehicle.label if task.vehicle is not None else None,
        location=task.location,
        instructions=task.instructions,
        status=task.status,
        cancelled=cancelled,
        created_at=task.created_at,
        routes_needing_cover=[]
        if cancelled
        else _routes_needing_cover(
            db,
            task.service_date,
            task.start_minute,
            task.end_minute,
            task.driver_id,
            task.vehicle_id,
        ),
    )


def _driver_read(task: DispatchTask) -> DriverDispatchTaskRead:
    return DriverDispatchTaskRead(
        id=task.id,
        kind=task.kind,
        service_date=task.service_date,
        start_minute=task.start_minute,
        end_minute=task.end_minute,
        vehicle_label=task.vehicle.label if task.vehicle is not None else None,
        location=task.location,
        instructions=task.instructions,
        status=task.status,
        cancelled=task.cancelled_at is not None,
    )


def _state(task: DispatchTask) -> dict:
    return {
        "kind": task.kind.value,
        "service_date": task.service_date.isoformat(),
        "start_minute": task.start_minute,
        "end_minute": task.end_minute,
        "driver_id": task.driver_id,
        "vehicle_id": task.vehicle_id,
        "location": task.location,
        "instructions": task.instructions,
        "status": task.status.value,
        "cancelled": task.cancelled_at is not None,
    }


def _resolve(db: Session, driver_id: int, vehicle_id: int | None) -> tuple[Driver, Vehicle | None]:
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    vehicle = None
    if vehicle_id is not None:
        vehicle = db.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown vehicle_id"
            )
    return driver, vehicle


def _check_window(start_minute: int, end_minute: int) -> None:
    if start_minute >= end_minute:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_minute must be before end_minute",
        )


def _refuse_if_blocked(blocking: list[str]) -> None:
    if blocking:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot assign this task: " + "; ".join(blocking),
        )


def _get(db: Session, task_id: int) -> DispatchTask:
    task = db.get(DispatchTask, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.post("", response_model=DispatchTaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: DispatchTaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> DispatchTaskRead:
    _check_window(payload.start_minute, payload.end_minute)
    driver, vehicle = _resolve(db, payload.driver_id, payload.vehicle_id)
    blocking, _ = _conflicts(
        db,
        service_date=payload.service_date,
        start_minute=payload.start_minute,
        end_minute=payload.end_minute,
        driver=driver,
        vehicle=vehicle,
    )
    _refuse_if_blocked(blocking)

    task = DispatchTask(
        kind=payload.kind,
        service_date=payload.service_date,
        start_minute=payload.start_minute,
        end_minute=payload.end_minute,
        driver_id=driver.id,
        vehicle_id=vehicle.id if vehicle is not None else None,
        location=payload.location,
        instructions=payload.instructions,
        created_by_user_id=current_user.id,
    )
    db.add(task)
    db.flush()
    record_audit(
        db,
        entity_type="dispatch_task",
        entity_id=task.id,
        action="created",
        actor=current_user,
        after_state=_state(task),
    )
    db.commit()
    db.refresh(task)
    return _read(db, task)


@router.get("", response_model=list[DispatchTaskRead])
def list_tasks(
    service_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[DispatchTaskRead]:
    tasks = (
        db.query(DispatchTask)
        .filter(DispatchTask.service_date == service_date)
        .order_by(DispatchTask.start_minute, DispatchTask.id)
        .all()
    )
    return [_read(db, t) for t in tasks]


@router.patch("/{task_id}", response_model=DispatchTaskRead)
def update_task(
    task_id: int,
    payload: DispatchTaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> DispatchTaskRead:
    task = _get(db, task_id)
    if task.cancelled_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This task was cancelled")
    fields = payload.model_fields_set
    for required in ("kind", "start_minute", "end_minute", "driver_id", "instructions", "status"):
        if required in fields and getattr(payload, required) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{required} can't be cleared",
            )

    # Checked against the prospective values, before anything changes.
    start = payload.start_minute if payload.start_minute is not None else task.start_minute
    end = payload.end_minute if payload.end_minute is not None else task.end_minute
    driver_id = payload.driver_id if payload.driver_id is not None else task.driver_id
    vehicle_id = payload.vehicle_id if "vehicle_id" in fields else task.vehicle_id
    _check_window(start, end)
    driver, vehicle = _resolve(db, driver_id, vehicle_id)
    if fields & {"start_minute", "end_minute", "driver_id", "vehicle_id"}:
        blocking, _ = _conflicts(
            db,
            service_date=task.service_date,
            start_minute=start,
            end_minute=end,
            driver=driver,
            vehicle=vehicle,
            exclude_task_id=task.id,
        )
        _refuse_if_blocked(blocking)

    before = _state(task)
    new_driver = driver.id != task.driver_id
    if payload.kind is not None:
        task.kind = payload.kind
    task.start_minute, task.end_minute = start, end
    task.driver_id, task.vehicle_id = driver.id, vehicle_id
    if "location" in fields:
        task.location = payload.location
    if payload.instructions is not None:
        task.instructions = payload.instructions
    if payload.status is not None and payload.status != task.status:
        task.status = payload.status
        task.status_updated_at = datetime.now(UTC)
    elif new_driver and resets_on_new_driver(task.status):
        # A new driver has to receive and acknowledge it themselves.
        task.status = AssignmentStatus.SENT
        task.status_updated_at = datetime.now(UTC)
    db.flush()
    db.refresh(task)
    record_audit(
        db,
        entity_type="dispatch_task",
        entity_id=task.id,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state=_state(task),
    )
    db.commit()
    return _read(db, task)


@router.post("/{task_id}/cancel", response_model=DispatchTaskRead)
def cancel_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> DispatchTaskRead:
    task = _get(db, task_id)
    if task.cancelled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This task is already cancelled"
        )
    if task.status == AssignmentStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This task is already completed"
        )
    before = _state(task)
    task.cancelled_at = datetime.now(UTC)
    db.flush()
    record_audit(
        db,
        entity_type="dispatch_task",
        entity_id=task.id,
        action="cancelled",
        actor=current_user,
        before_state=before,
        after_state=_state(task),
    )
    db.commit()
    db.refresh(task)
    return _read(db, task)


def _linked_driver_id(current_user: User) -> int:
    if current_user.driver_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This driver account is not linked to a Driver record",
        )
    return current_user.driver_id


def _my_tasks(db: Session, driver_id: int, service_date: date) -> list[DispatchTask]:
    return (
        db.query(DispatchTask)
        .filter(DispatchTask.driver_id == driver_id, DispatchTask.service_date == service_date)
        .order_by(DispatchTask.start_minute, DispatchTask.id)
        .all()
    )


@router.get("/mine/{service_date}", response_model=list[DriverDispatchTaskRead])
def list_my_tasks(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.DRIVER)),
) -> list[DriverDispatchTaskRead]:
    driver_id = _linked_driver_id(current_user)
    return [_driver_read(t) for t in _my_tasks(db, driver_id, service_date)]


@router.post("/mine/{service_date}/receipt", response_model=list[DriverDispatchTaskRead])
def acknowledge_task_receipt(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.DRIVER)),
) -> list[DriverDispatchTaskRead]:
    """Spec section 14's "Received" for tasks, as for assignments: only
    Sent, uncancelled tasks move, so it's idempotent; each move is audited."""
    driver_id = _linked_driver_id(current_user)
    mine = _my_tasks(db, driver_id, service_date)
    for task in mine:
        if task.status == AssignmentStatus.SENT and task.cancelled_at is None:
            task.status = AssignmentStatus.RECEIVED
            task.status_updated_at = datetime.now(UTC)
            db.flush()
            record_audit(
                db,
                entity_type="dispatch_task",
                entity_id=task.id,
                action="status_changed",
                actor=current_user,
                before_state={"status": AssignmentStatus.SENT.value},
                after_state={"status": AssignmentStatus.RECEIVED.value},
            )
    db.commit()
    return [_driver_read(t) for t in mine]


@router.patch("/{task_id}/status", response_model=DriverDispatchTaskRead)
def update_task_status(
    task_id: int,
    payload: AssignmentStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.DRIVER)),
) -> DriverDispatchTaskRead:
    """The driver reports progress on their own task: forward only."""
    task = _get(db, task_id)
    if task.driver_id != current_user.driver_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own tasks",
        )
    if task.cancelled_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Dispatch cancelled this task."
        )
    problem = driver_transition_problem(task.status, payload.status)
    if problem is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=problem)
    before_status = task.status
    if payload.status == before_status:
        return _driver_read(task)
    task.status = payload.status
    task.status_updated_at = datetime.now(UTC)
    db.flush()
    record_audit(
        db,
        entity_type="dispatch_task",
        entity_id=task.id,
        action="status_changed",
        actor=current_user,
        before_state={"status": before_status.value},
        after_state={"status": task.status.value},
    )
    db.commit()
    db.refresh(task)
    return _driver_read(task)
