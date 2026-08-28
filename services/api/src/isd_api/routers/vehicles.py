from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import Qualification, Role, User, Vehicle
from isd_api.schemas import VehicleCreate, VehicleRead
from isd_api.security import require_role

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def _resolve_qualifications(db: Session, codes: list[str]) -> list[Qualification]:
    if not codes:
        return []
    quals = db.query(Qualification).filter(Qualification.code.in_(codes)).all()
    found_codes = {q.code for q in quals}
    missing = set(codes) - found_codes
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown qualification code(s): {sorted(missing)}",
        )
    return quals


@router.post("", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Vehicle:
    vehicle = Vehicle(
        label=payload.label,
        nominal_capacity=payload.nominal_capacity,
        effective_capacity=payload.effective_capacity,
        qualifications=_resolve_qualifications(db, payload.qualification_codes),
    )
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.get("", response_model=list[VehicleRead])
def list_vehicles(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[Vehicle]:
    return list(db.query(Vehicle).order_by(Vehicle.id).all())
