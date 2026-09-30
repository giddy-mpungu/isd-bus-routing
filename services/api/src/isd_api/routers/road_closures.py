"""Road closures (spec section 10): dispatchers record a crash, a flooded
road or a police scene, and buses are routed around it. See
isd_api/closures.py."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api import closures, ridership_rules
from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Assignment, Crew, RoadClosure, Role, Run, User
from isd_api.schemas import (
    ClosureImpactRead,
    RoadClosureCreate,
    RoadClosureRead,
    RoadClosureUpdate,
)
from isd_api.security import require_role

router = APIRouter(prefix="/road-closures", tags=["road-closures"])

_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


def _state(c: RoadClosure) -> dict:
    return {
        "kind": c.kind.value,
        "note": c.note,
        "location_lat": c.location_lat,
        "location_lon": c.location_lon,
        "radius_m": c.radius_m,
        "starts_at": c.starts_at.isoformat(),
        "ends_at": c.ends_at.isoformat() if c.ends_at else None,
        "cleared": c.cleared_at is not None,
    }


def _todays_assignments(db: Session) -> list[Assignment]:
    rules = ridership_rules.load_rules(db)
    today = ridership_rules.district_now(rules).date()
    return (
        db.query(Assignment)
        .join(Run, Assignment.run_id == Run.id)
        .join(Crew, Assignment.crew_id == Crew.id)
        .filter(Run.service_date == today)
        .order_by(Assignment.start_minute)
        .all()
    )


def _read(
    db: Session, c: RoadClosure, active_ids: set[int], today: list[Assignment]
) -> RoadClosureRead:
    affected = []
    if c.id in active_ids:
        for a in today:
            for impact in closures.impacts(db, a, [c]):
                affected.append(
                    ClosureImpactRead(
                        assignment_id=a.id,
                        description=(
                            f"{a.run.school.name} {a.run.direction.value.upper()} run on "
                            f"{a.crew.vehicle.label}"
                        ),
                        stop_inside=impact.stop_inside,
                    )
                )
    return RoadClosureRead(
        id=c.id,
        kind=c.kind,
        note=c.note,
        location_lat=c.location_lat,
        location_lon=c.location_lon,
        radius_m=c.radius_m,
        starts_at=c.starts_at,
        ends_at=c.ends_at,
        cleared=c.cleared_at is not None,
        active=c.id in active_ids,
        affected_runs=affected,
    )


def _get(db: Session, closure_id: int) -> RoadClosure:
    closure = db.get(RoadClosure, closure_id)
    if closure is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Closure not found")
    return closure


def _check_times(starts_at: datetime, ends_at: datetime | None) -> None:
    if ends_at is not None and _utc(ends_at) <= _utc(starts_at):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="The end must be after the start"
        )


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


@router.post("", response_model=RoadClosureRead, status_code=status.HTTP_201_CREATED)
def create_closure(
    payload: RoadClosureCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> RoadClosureRead:
    starts_at = payload.starts_at or ridership_rules.utc_now()
    _check_times(starts_at, payload.ends_at)
    closure = RoadClosure(
        kind=payload.kind,
        note=payload.note,
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
        radius_m=payload.radius_m,
        starts_at=starts_at,
        ends_at=payload.ends_at,
        created_by_user_id=current_user.id,
    )
    db.add(closure)
    db.flush()
    record_audit(
        db,
        entity_type="road_closure",
        entity_id=closure.id,
        action="created",
        actor=current_user,
        after_state=_state(closure),
    )
    db.commit()
    db.refresh(closure)
    active = {c.id for c in closures.active_now(db)}
    return _read(db, closure, active, _todays_assignments(db))


@router.get("", response_model=list[RoadClosureRead])
def list_closures(
    include_ended: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_ROLES)),
) -> list[RoadClosureRead]:
    """In force now (with the runs they may affect today), plus ones still
    to come; ended and cleared ones too with `include_ended`."""
    now = ridership_rules.utc_now()
    active = {c.id for c in closures.active_now(db, now)}
    rows = db.query(RoadClosure).order_by(RoadClosure.starts_at.desc(), RoadClosure.id.desc())
    today = _todays_assignments(db)
    result = []
    for c in rows:
        upcoming = c.cleared_at is None and _utc(c.starts_at) > now
        if include_ended or c.id in active or upcoming:
            result.append(_read(db, c, active, today))
    return result


@router.patch("/{closure_id}", response_model=RoadClosureRead)
def update_closure(
    closure_id: int,
    payload: RoadClosureUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> RoadClosureRead:
    """Edit the note, the radius or the end (an explicit null makes it
    open-ended)."""
    closure = _get(db, closure_id)
    if closure.cleared_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This closure was cleared")
    sent = payload.model_fields_set
    ends_at = payload.ends_at if "ends_at" in sent else closure.ends_at
    _check_times(closure.starts_at, ends_at)
    before = _state(closure)
    if payload.note is not None:
        closure.note = payload.note
    if payload.radius_m is not None:
        closure.radius_m = payload.radius_m
    closure.ends_at = ends_at
    db.flush()
    record_audit(
        db,
        entity_type="road_closure",
        entity_id=closure.id,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state=_state(closure),
    )
    db.commit()
    db.refresh(closure)
    active = {c.id for c in closures.active_now(db)}
    return _read(db, closure, active, _todays_assignments(db))


@router.post("/{closure_id}/clear", response_model=RoadClosureRead)
def clear_closure(
    closure_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> RoadClosureRead:
    """The road is open again: buses stop avoiding it."""
    closure = _get(db, closure_id)
    if closure.cleared_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already cleared")
    before = _state(closure)
    closure.cleared_at = ridership_rules.utc_now()
    db.flush()
    record_audit(
        db,
        entity_type="road_closure",
        entity_id=closure.id,
        action="cleared",
        actor=current_user,
        before_state=before,
        after_state=_state(closure),
    )
    db.commit()
    db.refresh(closure)
    return _read(db, closure, set(), [])
