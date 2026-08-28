from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import Role, Stop, User
from isd_api.schemas import StopCreate, StopRead
from isd_api.security import require_role

router = APIRouter(prefix="/stops", tags=["stops"])


@router.post("", response_model=StopRead, status_code=status.HTTP_201_CREATED)
def create_stop(
    payload: StopCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Stop:
    """spec section 3: "Transportation personnel must be able to
    approve, reject, relocate, or manually create stops" — manual
    creation only in this phase; automated stop-generation from
    walking-distance/road-safety constraints needs GIS data this
    project doesn't have yet."""
    stop = Stop(
        label=payload.label,
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
    )
    db.add(stop)
    db.commit()
    db.refresh(stop)
    return stop


@router.get("", response_model=list[StopRead])
def list_stops(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[Stop]:
    return list(db.query(Stop).order_by(Stop.id).all())
