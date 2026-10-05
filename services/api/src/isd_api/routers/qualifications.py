from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Qualification, Role, User
from isd_api.schemas import QualificationCreate, QualificationRead, QualificationUpdate
from isd_api.security import require_role

router = APIRouter(prefix="/qualifications", tags=["qualifications"])


@router.post("", response_model=QualificationRead, status_code=status.HTTP_201_CREATED)
def create_qualification(
    payload: QualificationCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Qualification:
    if db.query(Qualification).filter(Qualification.code == payload.code).one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code already exists")
    qualification = Qualification(
        code=payload.code, kind=payload.kind, description=payload.description
    )
    db.add(qualification)
    db.commit()
    db.refresh(qualification)
    return qualification


@router.get("", response_model=list[QualificationRead])
def list_qualifications(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[Qualification]:
    """Staff only (least privilege, audit 2026-10-04): only the
    dispatcher console uses it. Active and inactive alike -- see
    list_vehicles' identical note. Frontend pickers that assign a
    qualification to a driver/vehicle/run filter to active."""
    return list(db.query(Qualification).order_by(Qualification.id).all())


@router.patch("/{qualification_id}", response_model=QualificationRead)
def update_qualification(
    qualification_id: int,
    payload: QualificationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Qualification:
    """Edits a qualification's description, and/or retires it. `code`/
    `kind` are immutable after creation -- see QualificationUpdate's
    own docstring for why."""
    qualification = db.get(Qualification, qualification_id)
    if qualification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Qualification not found")

    before_state = {"description": qualification.description, "is_active": qualification.is_active}
    if payload.description is not None:
        qualification.description = payload.description
    if payload.is_active is not None:
        qualification.is_active = payload.is_active

    db.flush()
    record_audit(
        db,
        entity_type="qualification",
        entity_id=qualification.id,
        action="updated",
        actor=current_user,
        before_state=before_state,
        after_state={
            "description": qualification.description,
            "is_active": qualification.is_active,
        },
    )
    db.commit()
    db.refresh(qualification)
    return qualification
