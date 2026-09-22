from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Role, Stop, Student, User
from isd_api.schemas import StopCreate, StopRead, StopUpdate
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


@router.patch("/{stop_id}", response_model=StopRead)
def update_stop(
    stop_id: int,
    payload: StopUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Stop:
    """ "Relocate" a stop (spec section 3.1/21) — rename and/or move it.
    Always safe: unlike deleting, a Student.stop_id keeps pointing at
    the same row, just with corrected details."""
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stop not found")

    before_state = {
        "label": stop.label,
        "location_lat": stop.location_lat,
        "location_lon": stop.location_lon,
    }
    if payload.label is not None:
        stop.label = payload.label
    if payload.location_lat is not None:
        stop.location_lat = payload.location_lat
    if payload.location_lon is not None:
        stop.location_lon = payload.location_lon

    db.flush()
    record_audit(
        db,
        entity_type="stop",
        entity_id=stop.id,
        action="updated",
        actor=current_user,
        before_state=before_state,
        after_state={
            "label": stop.label,
            "location_lat": stop.location_lat,
            "location_lon": stop.location_lon,
        },
    )
    db.commit()
    db.refresh(stop)
    return stop


@router.delete("/{stop_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stop(
    stop_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> None:
    """spec section 3.1: "reject ... stops". Only when unreferenced —
    unlike Vehicle/Driver/Qualification, a Stop genuinely can be
    removed outright once nothing points at it, since nothing else
    (no historical Assignment, no audit-relevant record) is keyed by
    stop_id except Student — and a student still assigned to this stop
    means deleting it would silently orphan that assignment, which this
    system never does silently (spec section 21: no guessing)."""
    stop = db.get(Stop, stop_id)
    if stop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stop not found")

    in_use = db.query(Student).filter(Student.stop_id == stop_id).count()
    if in_use:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{in_use} student(s) are still assigned to this stop — reassign them first",
        )

    record_audit(
        db,
        entity_type="stop",
        entity_id=stop.id,
        action="deleted",
        actor=current_user,
        before_state={
            "label": stop.label,
            "location_lat": stop.location_lat,
            "location_lon": stop.location_lon,
        },
    )
    db.delete(stop)
    db.commit()
