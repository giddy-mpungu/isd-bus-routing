from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import Qualification, Role, User
from isd_api.schemas import QualificationCreate, QualificationRead
from isd_api.security import get_current_user, require_role

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
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[Qualification]:
    return list(db.query(Qualification).order_by(Qualification.id).all())
