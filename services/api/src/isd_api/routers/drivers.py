from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import Driver, Role, User
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.schemas import DriverCreate, DriverRead
from isd_api.security import require_role

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post("", response_model=DriverRead, status_code=status.HTTP_201_CREATED)
def create_driver(
    payload: DriverCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Driver:
    driver = Driver(
        full_name=payload.full_name,
        max_continuous_minutes=payload.max_continuous_minutes,
        qualifications=_resolve_qualifications(db, payload.qualification_codes),
    )
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@router.get("", response_model=list[DriverRead])
def list_drivers(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[Driver]:
    return list(db.query(Driver).order_by(Driver.id).all())
