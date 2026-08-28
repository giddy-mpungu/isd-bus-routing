from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import Crew, Driver, Role, User, Vehicle
from isd_api.schemas import CrewCreate, CrewRead
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
    if db.get(Driver, payload.driver_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    if db.get(Vehicle, payload.vehicle_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown vehicle_id")

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
