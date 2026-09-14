"""spec section 12: field trips and special assignments, scheduled
through the same system as regular routes but NOT run through the
CP-SAT solver -- assigning a driver/vehicle here is a manual
dispatcher decision (spec section 21), the same shape as Phase 6's
substitute-coverage ranking.

Deliberately first-slice scoped:
- **Same-day trips only** (`departure_at`/`expected_return_at` must
  share a calendar date) -- keeps conflict-checking a single-day
  minute-of-day comparison, matching how `Run`/`Assignment`/`Crew`
  already work everywhere else in this codebase. Overnight trips are a
  real but rarer case, named as a follow-up, not silently mishandled.
- **Conflict detection (spec section 12.1) only checks what this
  system actually models**: overlapping regular-route `Assignment`s
  and overlapping other `FieldTrip`s, for the proposed driver and/or
  vehicle. Training, maintenance, and required-break conflicts are
  named in the spec but have no corresponding entity in this schema
  (no Training or Maintenance model exists) -- checking them would be
  fabricating a signal this system doesn't have, the same reasoning
  PR #16 used to skip a driver-license-vs-vehicle-type check.
- **Spec section 12.2's "delay management" is not a separate
  mechanism.** `GET /field-trips/{id}/conflicts` is the reevaluation:
  call it again after `PATCH`ing `expected_return_at` (a delay) to see
  whether the trip's assigned driver/vehicle now conflicts with a
  regular route -- there's no new "flag as needing substitute" state;
  the dispatcher acts on what the conflict list shows, using the
  existing `GET /drivers/{id}/substitute-candidates` flow if needed.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import (
    Assignment,
    Crew,
    Driver,
    FieldTrip,
    Role,
    Run,
    TripStatus,
    User,
    Vehicle,
)
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.schemas import (
    FieldTripConflictCheck,
    FieldTripCreate,
    FieldTripRead,
    FieldTripUpdate,
)
from isd_api.security import require_role

router = APIRouter(prefix="/field-trips", tags=["field-trips"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


def _minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


@router.post("", response_model=FieldTripRead, status_code=status.HTTP_201_CREATED)
def create_field_trip(
    payload: FieldTripCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> FieldTrip:
    if payload.departure_at.date() != payload.expected_return_at.date():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="departure_at and expected_return_at must be on the same calendar date "
            "(overnight field trips are not supported in this slice)",
        )
    if payload.departure_at >= payload.expected_return_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="departure_at must be before expected_return_at",
        )

    trip = FieldTrip(
        requesting_party=payload.requesting_party,
        origin=payload.origin,
        destination=payload.destination,
        departure_at=payload.departure_at,
        expected_return_at=payload.expected_return_at,
        passenger_count=payload.passenger_count,
        trip_contact=payload.trip_contact,
        bus_assistant_name=payload.bus_assistant_name,
        special_instructions=payload.special_instructions,
        required_qualifications=_resolve_qualifications(db, payload.required_qualification_codes),
    )
    db.add(trip)
    db.flush()
    record_audit(
        db,
        entity_type="field_trip",
        entity_id=trip.id,
        action="created",
        actor=current_user,
        after_state={
            "requesting_party": trip.requesting_party,
            "departure_at": trip.departure_at.isoformat(),
            "status": trip.status.value,
        },
    )
    db.commit()
    db.refresh(trip)
    return trip


@router.get("", response_model=list[FieldTripRead])
def list_field_trips(
    departure_date: date | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[FieldTrip]:
    trips = db.query(FieldTrip).order_by(FieldTrip.departure_at).all()
    if departure_date is not None:
        # SQLite has no native DATE() comparison against a stored
        # datetime column via the ORM in a portable way, so filter in
        # Python -- this table is small (operational field trips, not
        # a high-volume entity), so this isn't a real performance
        # concern at this project's scale.
        return [t for t in trips if t.departure_at.date() == departure_date]
    return trips


@router.get("/{trip_id}", response_model=FieldTripRead)
def get_field_trip(
    trip_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> FieldTrip:
    trip = db.get(FieldTrip, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field trip not found")
    return trip


@router.patch("/{trip_id}", response_model=FieldTripRead)
def update_field_trip(
    trip_id: int,
    payload: FieldTripUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> FieldTrip:
    trip = db.get(FieldTrip, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field trip not found")
    if (
        payload.assigned_driver_id is not None
        and db.get(Driver, payload.assigned_driver_id) is None
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    if (
        payload.assigned_vehicle_id is not None
        and db.get(Vehicle, payload.assigned_vehicle_id) is None
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown vehicle_id")

    before_state = {
        "status": trip.status.value,
        "assigned_driver_id": trip.assigned_driver_id,
        "assigned_vehicle_id": trip.assigned_vehicle_id,
        "expected_return_at": trip.expected_return_at.isoformat(),
        "actual_return_at": trip.actual_return_at.isoformat() if trip.actual_return_at else None,
    }
    if payload.status is not None:
        trip.status = payload.status
    if payload.assigned_driver_id is not None:
        trip.assigned_driver_id = payload.assigned_driver_id
    if payload.assigned_vehicle_id is not None:
        trip.assigned_vehicle_id = payload.assigned_vehicle_id
    if payload.expected_return_at is not None:
        if payload.expected_return_at.date() != trip.departure_at.date():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="expected_return_at must stay on the same calendar date as departure_at",
            )
        trip.expected_return_at = payload.expected_return_at
    if payload.actual_return_at is not None:
        trip.actual_return_at = payload.actual_return_at
    db.flush()
    record_audit(
        db,
        entity_type="field_trip",
        entity_id=trip.id,
        action="updated",
        actor=current_user,
        before_state=before_state,
        after_state={
            "status": trip.status.value,
            "assigned_driver_id": trip.assigned_driver_id,
            "assigned_vehicle_id": trip.assigned_vehicle_id,
            "expected_return_at": trip.expected_return_at.isoformat(),
            "actual_return_at": trip.actual_return_at.isoformat()
            if trip.actual_return_at
            else None,
        },
    )
    db.commit()
    db.refresh(trip)
    return trip


@router.get("/{trip_id}/conflicts", response_model=FieldTripConflictCheck)
def check_field_trip_conflicts(
    trip_id: int,
    driver_id: int | None = None,
    vehicle_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> FieldTripConflictCheck:
    """spec section 12.1, checked BEFORE assigning (per driver_id/
    vehicle_id query params, which need not match the trip's current
    assignment yet) -- and re-checkable after any PATCH as section
    12.2's delay-management reevaluation. See module docstring for
    what this deliberately does and doesn't check."""
    trip = db.get(FieldTrip, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field trip not found")
    driver_id = driver_id if driver_id is not None else trip.assigned_driver_id
    vehicle_id = vehicle_id if vehicle_id is not None else trip.assigned_vehicle_id
    if driver_id is None and vehicle_id is None:
        return FieldTripConflictCheck(conflicts=[])

    trip_date = trip.departure_at.date()
    trip_start = _minute_of_day(trip.departure_at)
    trip_end = _minute_of_day(trip.expected_return_at)
    conflicts: list[str] = []

    crew_query = db.query(Crew).filter(Crew.service_date == trip_date)
    if driver_id is not None and vehicle_id is not None:
        crew_query = crew_query.filter(
            or_(Crew.driver_id == driver_id, Crew.vehicle_id == vehicle_id)
        )
    elif driver_id is not None:
        crew_query = crew_query.filter(Crew.driver_id == driver_id)
    else:
        crew_query = crew_query.filter(Crew.vehicle_id == vehicle_id)
    crew_ids = [c.id for c in crew_query.all()]
    if crew_ids:
        overlapping = (
            db.query(Assignment)
            .join(Run, Assignment.run_id == Run.id)
            .filter(
                Assignment.crew_id.in_(crew_ids),
                Assignment.start_minute < trip_end,
                Assignment.end_minute > trip_start,
            )
            .all()
        )
        for assignment in overlapping:
            conflicts.append(
                f"Regular route at {assignment.run.school.name} "
                f"({assignment.start_minute}-{assignment.end_minute}) overlaps this trip"
            )

    other_trips_query = db.query(FieldTrip).filter(
        FieldTrip.id != trip_id,
        FieldTrip.status != TripStatus.COMPLETED,
    )
    if driver_id is not None and vehicle_id is not None:
        other_trips_query = other_trips_query.filter(
            or_(
                FieldTrip.assigned_driver_id == driver_id,
                FieldTrip.assigned_vehicle_id == vehicle_id,
            )
        )
    elif driver_id is not None:
        other_trips_query = other_trips_query.filter(FieldTrip.assigned_driver_id == driver_id)
    else:
        other_trips_query = other_trips_query.filter(FieldTrip.assigned_vehicle_id == vehicle_id)
    for other in other_trips_query.all():
        if other.departure_at.date() != trip_date:
            continue
        other_start = _minute_of_day(other.departure_at)
        other_end = _minute_of_day(other.expected_return_at)
        if other_start < trip_end and other_end > trip_start:
            conflicts.append(
                f"Field trip #{other.id} to {other.destination} "
                f"({other.departure_at.strftime('%H:%M')}-"
                f"{other.expected_return_at.strftime('%H:%M')}) overlaps this trip"
            )

    return FieldTripConflictCheck(conflicts=conflicts)
