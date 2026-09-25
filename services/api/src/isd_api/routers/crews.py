from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from isd_api.assignment_states import resets_on_new_driver
from isd_api.availability import driver_conflict_for_window, pairing_problem
from isd_api.db import get_db
from isd_api.licensing import license_violation
from isd_api.models import AssignmentStatus, Crew, Driver, Role, User, Vehicle
from isd_api.routers.announcements import _maybe_create_substitution_announcement
from isd_api.schemas import CrewCreate, CrewDriverUpdate, CrewRead
from isd_api.security import require_role

router = APIRouter(prefix="/crews", tags=["crews"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)
_READ_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


@router.post("", response_model=CrewRead, status_code=status.HTTP_201_CREATED)
def create_crew(
    payload: CrewCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> Crew:
    if payload.available_window_earliest > payload.available_window_latest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="available_window_earliest must be <= available_window_latest",
        )
    driver = db.get(Driver, payload.driver_id)
    if driver is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    vehicle = db.get(Vehicle, payload.vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown vehicle_id")
    # Spec section 2.1: never pair an out-of-service vehicle or a
    # deactivated driver into a crew in the first place.
    unavailable = pairing_problem(driver, vehicle)
    if unavailable is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot create crew: {unavailable}"
        )

    crew = Crew(
        service_date=payload.service_date,
        driver_id=payload.driver_id,
        vehicle_id=payload.vehicle_id,
        available_window_earliest=payload.available_window_earliest,
        available_window_latest=payload.available_window_latest,
    )
    db.add(crew)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This driver or vehicle already has a crew for that service_date",
        ) from exc
    db.refresh(crew)
    return crew


@router.get("", response_model=list[CrewRead])
def list_crews(
    service_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_READ_ROLES)),
) -> list[Crew]:
    return list(db.query(Crew).filter(Crew.service_date == service_date).order_by(Crew.id).all())


@router.patch("/{crew_id}", response_model=CrewRead)
def update_crew_driver(
    crew_id: int,
    payload: CrewDriverUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> Crew:
    """Repoints an existing crew's driver, keeping its vehicle/date/
    assignments unchanged — spec section 13.2: "Bus 724 should remain
    available for assignment to another qualified driver" when its own
    driver is absent. Vehicle+service_date is already claimed by this
    crew row (UniqueConstraint), so a substitute can't get the freed
    vehicle via a second POST /crews; repointing this row is the way.
    Note: every assignment still on this crew moves with it — if the
    absent driver's day needs splitting across multiple substitutes
    (spec section 13.1 explicitly allows this), that's not what a
    single PATCH here does; each assignment would need its own crew,
    which needs a free vehicle to pair with.

    A genuine driver change on a crew with existing assignments may
    fire an auto-generated family-facing substitution notice -- see
    routers/announcements._maybe_create_substitution_announcement."""
    crew = db.get(Crew, crew_id)
    if crew is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    new_driver = db.get(Driver, payload.driver_id)
    if new_driver is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    unlicensed = license_violation(new_driver, crew.vehicle)
    if unlicensed is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot assign {new_driver.full_name} to this crew: {unlicensed}",
        )
    # The substitute must actually be free for every assignment the crew
    # carries (spec section 13: availability is a scheduling constraint).
    for assignment in crew.assignments:
        conflict = driver_conflict_for_window(
            db,
            new_driver,
            crew.service_date,
            assignment.start_minute,
            assignment.end_minute,
        )
        if conflict is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot assign {new_driver.full_name} to this crew: {conflict}",
            )

    driver_changed = payload.driver_id != crew.driver_id
    crew.driver_id = payload.driver_id
    if driver_changed:
        for assignment in crew.assignments:
            if resets_on_new_driver(assignment.status):
                assignment.status = AssignmentStatus.SENT
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This driver already has a crew for that service_date",
        ) from exc
    if driver_changed:
        _maybe_create_substitution_announcement(db, crew, current_user)
    db.commit()
    db.refresh(crew)
    return crew
