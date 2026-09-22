from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Qualification, Role, User, Vehicle
from isd_api.schemas import VehicleCreate, VehicleRead, VehicleUpdate
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
        length_m=payload.length_m,
        width_m=payload.width_m,
        height_m=payload.height_m,
        weight_kg=payload.weight_kg,
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
    """Returns active and inactive vehicles alike -- an admin managing
    the fleet needs to see (and potentially reactivate) a retired one.
    services/web filters this down to active-only for crew-creation
    pickers; nothing else needs to."""
    return list(db.query(Vehicle).order_by(Vehicle.id).all())


@router.patch("/{vehicle_id}", response_model=VehicleRead)
def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Vehicle:
    """Edits an existing vehicle's profile, and/or retires it
    (is_active=False) -- spec section 21 "reassign buses" /
    ADR 0007's fleet-maintenance note. Never a hard delete: a Crew,
    Assignment, FieldTrip, or CrewTemplate created while this vehicle
    was active must keep meaning what it always meant."""
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

    before_state = {
        "label": vehicle.label,
        "nominal_capacity": vehicle.nominal_capacity,
        "effective_capacity": vehicle.effective_capacity,
        "length_m": vehicle.length_m,
        "width_m": vehicle.width_m,
        "height_m": vehicle.height_m,
        "weight_kg": vehicle.weight_kg,
        "is_active": vehicle.is_active,
        "qualification_codes": sorted(q.code for q in vehicle.qualifications),
    }

    if payload.label is not None:
        vehicle.label = payload.label
    if payload.nominal_capacity is not None:
        vehicle.nominal_capacity = payload.nominal_capacity
    if payload.effective_capacity is not None:
        vehicle.effective_capacity = payload.effective_capacity
    if payload.length_m is not None:
        vehicle.length_m = payload.length_m
    if payload.width_m is not None:
        vehicle.width_m = payload.width_m
    if payload.height_m is not None:
        vehicle.height_m = payload.height_m
    if payload.weight_kg is not None:
        vehicle.weight_kg = payload.weight_kg
    if payload.is_active is not None:
        vehicle.is_active = payload.is_active
    if payload.qualification_codes is not None:
        vehicle.qualifications = _resolve_qualifications(db, payload.qualification_codes)

    db.flush()
    record_audit(
        db,
        entity_type="vehicle",
        entity_id=vehicle.id,
        action="updated",
        actor=current_user,
        before_state=before_state,
        after_state={
            "label": vehicle.label,
            "nominal_capacity": vehicle.nominal_capacity,
            "effective_capacity": vehicle.effective_capacity,
            "length_m": vehicle.length_m,
            "width_m": vehicle.width_m,
            "height_m": vehicle.height_m,
            "weight_kg": vehicle.weight_kg,
            "is_active": vehicle.is_active,
            "qualification_codes": sorted(q.code for q in vehicle.qualifications),
        },
    )
    db.commit()
    db.refresh(vehicle)
    return vehicle
