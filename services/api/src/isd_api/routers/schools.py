from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import Role, School, User
from isd_api.schemas import SchoolCreate, SchoolRead
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/schools", tags=["schools"])


@router.post("", response_model=SchoolRead, status_code=status.HTTP_201_CREATED)
def create_school(
    payload: SchoolCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> School:
    school = School(
        name=payload.name, location_lat=payload.location_lat, location_lon=payload.location_lon
    )
    db.add(school)
    db.commit()
    db.refresh(school)
    return school


@router.get("", response_model=list[SchoolRead])
def list_schools(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[School]:
    return list(db.query(School).order_by(School.id).all())
