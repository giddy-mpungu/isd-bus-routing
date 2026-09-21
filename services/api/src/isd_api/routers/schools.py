from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Role, School, User
from isd_api.schemas import SchoolCreate, SchoolRead, SchoolUpdate
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/schools", tags=["schools"])


@router.post("", response_model=SchoolRead, status_code=status.HTTP_201_CREATED)
def create_school(
    payload: SchoolCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> School:
    school = School(
        name=payload.name,
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
        external_id=payload.external_id,
    )
    db.add(school)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another school already has that SIS ID",
        ) from exc
    db.refresh(school)
    return school


@router.patch("/{school_id}", response_model=SchoolRead)
def update_school(
    school_id: int,
    payload: SchoolUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> School:
    """Sets or clears the SIS mapping (OneRoster org sourcedId) used by
    the roster import. Nothing else about a school is editable here."""
    school = db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    before = {"external_id": school.external_id}
    school.external_id = payload.external_id
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another school already has that SIS ID",
        ) from exc
    record_audit(
        db,
        entity_type="school",
        entity_id=school.id,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state={"external_id": school.external_id},
    )
    db.commit()
    db.refresh(school)
    return school


@router.get("", response_model=list[SchoolRead])
def list_schools(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[School]:
    return list(db.query(School).order_by(School.id).all())
