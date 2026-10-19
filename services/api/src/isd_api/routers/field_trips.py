"""spec section 12: field trips and special assignments.

Assigning a driver and vehicle to a trip is a manual dispatcher decision
(spec section 21), but once assigned, a trip is a job in the same
scheduling engine as regular routes: `isd_api.availability` treats it as
busy time for that driver and that bus, padded by
FIELD_TRIP_TURNAROUND_MINUTES on each side. So the solver, manual
reassignment, crew repointing and substitute ranking all respect it. A
trip whose actual return has been recorded uses that; otherwise its
expected return.

- **Overnight (multi-day) trips** are split into one (date, start_minute,
  end_minute) window per calendar day (`availability.daily_windows`).
- **Conflicts (section 12.1)**: out-of-service bus, deactivated or absent
  driver, another field trip or a dispatch task, and regular routes. All
  but the last refuse
  the assignment (409). A regular-route clash doesn't: the dispatcher may
  prioritise the trip, and that route is then flagged "needs cover".
  Training, maintenance and required-break conflicts have no entity in
  this schema yet, so they aren't checked.
- **Delay management (section 12.2)**: a changed return time is always
  accepted, since it reports reality. Any regular route it now overlaps
  immediately shows `availability_issue` ("on field trip #N ...") on the
  schedule. `GET /field-trips/{id}/conflicts` lists those routes in
  `routes_needing_cover`, and a re-solve moves unlocked ones to another
  crew.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.availability import (
    FIELD_TRIP_TURNAROUND_MINUTES,
    daily_windows,
    driver_absences,
    tasks_blocking,
    trip_return,
    trip_windows,
    vehicle_blocks,
)
from isd_api.db import get_db
from isd_api.licensing import license_violation
from isd_api.models import (
    Assignment,
    Crew,
    DestinationProfile,
    Driver,
    FieldTrip,
    Role,
    TripStatus,
    User,
    Vehicle,
)
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.schemas import (
    DestinationProfileRead,
    DriverFieldTripRead,
    FieldTripConflictCheck,
    FieldTripCreate,
    FieldTripObservedDurationRead,
    FieldTripRead,
    FieldTripUpdate,
)
from isd_api.security import require_role

router = APIRouter(prefix="/field-trips", tags=["field-trips"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


def _naive(dt: datetime) -> datetime:
    """Strips tzinfo before comparing two datetimes -- this router
    treats timestamps as wall-clock only (see module docstring's
    minute-of-day design), and a value fresh off a request payload
    (which Pydantic parses as timezone-aware when the client sends an
    offset) is otherwise not directly comparable to the same value
    read back from SQLite, which round-trips as naive regardless of
    what was stored."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _windows_overlap(a: list[tuple[date, int, int]], b: list[tuple[date, int, int]]) -> bool:
    return any(
        a_date == b_date and a_start < b_end and b_start < a_end
        for a_date, a_start, a_end in a
        for b_date, b_start, b_end in b
    )


@router.post("", response_model=FieldTripRead, status_code=status.HTTP_201_CREATED)
def create_field_trip(
    payload: FieldTripCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> FieldTrip:
    if _naive(payload.departure_at) >= _naive(payload.expected_return_at):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="departure_at must be before expected_return_at",
        )
    if (
        payload.destination_profile_id is not None
        and db.get(DestinationProfile, payload.destination_profile_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown destination_profile_id"
        )

    trip = FieldTrip(
        requesting_party=payload.requesting_party,
        origin=payload.origin,
        destination=payload.destination,
        destination_profile_id=payload.destination_profile_id,
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


@router.get("/observed-duration", response_model=FieldTripObservedDurationRead)
def get_field_trip_observed_duration(
    destination: str | None = None,
    destination_profile_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> FieldTripObservedDurationRead:
    """spec section 20 applied to field trips -- see
    FieldTripObservedDurationRead's docstring for why this needs no
    audit-log lookup, unlike GET /runs/observed-duration. Decision
    support only (spec section 21): a dispatcher reads this and
    manually sets expected_return_at on a new trip; nothing here
    writes to a field trip automatically."""
    if destination is None and destination_profile_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide destination or destination_profile_id",
        )
    query = db.query(FieldTrip).filter(
        FieldTrip.status == TripStatus.COMPLETED, FieldTrip.actual_return_at.isnot(None)
    )
    query = (
        query.filter(FieldTrip.destination_profile_id == destination_profile_id)
        if destination_profile_id is not None
        else query.filter(FieldTrip.destination == destination)
    )

    samples: list[tuple[date, float]] = []
    for trip in query.all():
        if trip.actual_return_at is None:
            continue
        minutes = (trip.actual_return_at - trip.departure_at).total_seconds() / 60
        if minutes > 0:
            samples.append((trip.departure_at.date(), minutes))

    if not samples:
        return FieldTripObservedDurationRead(
            sample_count=0,
            average_actual_minutes=None,
            most_recent_actual_minutes=None,
            most_recent_departure_date=None,
        )

    samples.sort(key=lambda s: s[0])
    average = sum(minutes for _, minutes in samples) / len(samples)
    most_recent_date, most_recent_minutes = samples[-1]
    return FieldTripObservedDurationRead(
        sample_count=len(samples),
        average_actual_minutes=round(average, 1),
        most_recent_actual_minutes=round(most_recent_minutes),
        most_recent_departure_date=most_recent_date,
    )


@router.get("/mine/{service_date}", response_model=list[DriverFieldTripRead])
def list_my_field_trips(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.DRIVER)),
) -> list[DriverFieldTripRead]:
    """Spec sections 11 and 14: field trips are part of the assigned
    driver's day, so the tablet lists them alongside runs and tasks. Only
    trips assigned to this driver that touch `service_date`."""
    if current_user.driver_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This driver account is not linked to a Driver record",
        )
    trips = (
        db.query(FieldTrip)
        .filter(FieldTrip.assigned_driver_id == current_user.driver_id)
        .order_by(FieldTrip.departure_at)
        .all()
    )
    results = []
    for trip in trips:
        for day, start, end in trip_windows(trip, padded=False):
            if day != service_date:
                continue
            results.append(
                DriverFieldTripRead(
                    id=trip.id,
                    status=trip.status,
                    requesting_party=trip.requesting_party,
                    origin=trip.origin,
                    destination=trip.destination,
                    departure_at=trip.departure_at,
                    return_at=trip_return(trip),
                    start_minute=start,
                    end_minute=end,
                    passenger_count=trip.passenger_count,
                    vehicle_label=trip.assigned_vehicle.label
                    if trip.assigned_vehicle is not None
                    else None,
                    bus_assistant_name=trip.bus_assistant_name,
                    trip_contact=trip.trip_contact,
                    special_instructions=trip.special_instructions,
                    destination_profile=DestinationProfileRead.model_validate(
                        trip.destination_profile
                    )
                    if trip.destination_profile is not None
                    else None,
                )
            )
    return results


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
    if (
        payload.destination_profile_id is not None
        and db.get(DestinationProfile, payload.destination_profile_id) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown destination_profile_id"
        )

    # Spec section 12.1: assigning a driver or bus that can't do the trip
    # (out of service, deactivated, absent, or already on another trip) is
    # refused. A clash with a regular route is not: that route gets flagged
    # as needing cover instead. A changed return time is always accepted
    # (it reports reality); what it now clashes with is surfaced by the
    # conflicts check and the schedule's "needs cover" flags (section 12.2).
    # Checked against the prospective values, before anything is changed.
    if payload.assigned_driver_id is not None or payload.assigned_vehicle_id is not None:
        returns_at = payload.actual_return_at or trip.actual_return_at
        returns_at = returns_at or payload.expected_return_at or trip.expected_return_at
        pad = timedelta(minutes=FIELD_TRIP_TURNAROUND_MINUTES)
        blocking, _ = _trip_conflicts(
            db,
            trip,
            payload.assigned_driver_id
            if payload.assigned_driver_id is not None
            else trip.assigned_driver_id,
            payload.assigned_vehicle_id
            if payload.assigned_vehicle_id is not None
            else trip.assigned_vehicle_id,
            windows=daily_windows(trip.departure_at - pad, returns_at + pad),
        )
        if blocking:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot assign this trip: " + "; ".join(blocking),
            )

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
    if payload.destination_profile_id is not None:
        trip.destination_profile_id = payload.destination_profile_id
    if payload.expected_return_at is not None:
        if _naive(payload.expected_return_at) <= _naive(trip.departure_at):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="expected_return_at must be after departure_at",
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


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _trip_conflicts(
    db: Session,
    trip: FieldTrip,
    driver_id: int | None,
    vehicle_id: int | None,
    *,
    windows: list[tuple[date, int, int]] | None = None,
) -> tuple[list[str], list[str]]:
    """Spec section 12.1 for a proposed driver and/or vehicle.

    Returns (blocking, route_overlaps). Blocking conflicts make the
    assignment invalid: an out-of-service bus, a deactivated or absent
    driver, or another field trip. Route overlaps are regular assignments
    the trip would take the driver or bus away from; they don't block,
    because the dispatcher may prioritise the trip, but each such route
    is then flagged "needs cover" on the schedule (section 12.2).
    Both use the trip's window padded by FIELD_TRIP_TURNAROUND_MINUTES."""
    windows = windows if windows is not None else trip_windows(trip)
    blocking: list[str] = []
    route_overlaps: list[str] = []

    driver = db.get(Driver, driver_id) if driver_id is not None else None
    vehicle = db.get(Vehicle, vehicle_id) if vehicle_id is not None else None
    # Spec section 15: never more passengers than the bus may carry.
    capacity = vehicle.allowable_capacity() if vehicle is not None else None
    if vehicle is not None and capacity is not None and trip.passenger_count > capacity:
        blocking.append(
            f"Vehicle {vehicle.label} carries {capacity}; this trip has "
            f"{trip.passenger_count} passengers"
        )
    if vehicle is not None and not vehicle.is_active:
        blocking.append(f"Vehicle {vehicle.label} is out of service")
    elif vehicle is not None:
        for day, start, end in windows:
            for block_start, block_end, label in vehicle_blocks(db, vehicle, day):
                if start < block_end and block_start < end:
                    blocking.append(f"{label[0].upper()}{label[1:]} on {day}")
    if driver is not None:
        if not driver.is_active:
            blocking.append(f"Driver {driver.full_name} is deactivated")
        for day, start, end in windows:
            for absence in driver_absences(db, driver.id, day):
                if start < absence.end_minute and absence.start_minute < end:
                    blocking.append(
                        f"Driver {driver.full_name} is absent on {day} "
                        f"({absence.reason.value.replace('_', ' ')}, "
                        f"{_hhmm(absence.start_minute)}-{_hhmm(absence.end_minute)})"
                    )

    if driver is not None and vehicle is not None:
        unlicensed = license_violation(driver, vehicle)
        if unlicensed is not None:
            blocking.append(unlicensed[0].upper() + unlicensed[1:])

    trip_dates = {d for d, _, _ in windows}
    resource_filters = []
    if driver_id is not None:
        resource_filters.append(Crew.driver_id == driver_id)
    if vehicle_id is not None:
        resource_filters.append(Crew.vehicle_id == vehicle_id)
    if resource_filters:
        assignments = (
            db.query(Assignment)
            .join(Crew, Assignment.crew_id == Crew.id)
            .filter(Crew.service_date.in_(trip_dates), or_(*resource_filters))
            .order_by(Crew.service_date, Assignment.start_minute)
            .all()
        )
        for assignment in assignments:
            window = [
                (assignment.crew.service_date, assignment.start_minute, assignment.end_minute)
            ]
            if _windows_overlap(windows, window):
                route_overlaps.append(
                    f"Regular route at {assignment.run.school.name} on "
                    f"{assignment.crew.service_date} ({_hhmm(assignment.start_minute)}-"
                    f"{_hhmm(assignment.end_minute)}) overlaps this trip"
                )

    trip_filters = []
    if driver_id is not None:
        trip_filters.append(FieldTrip.assigned_driver_id == driver_id)
    if vehicle_id is not None:
        trip_filters.append(FieldTrip.assigned_vehicle_id == vehicle_id)
    if trip_filters:
        others = (
            db.query(FieldTrip)
            .filter(
                FieldTrip.id != trip.id,
                FieldTrip.status != TripStatus.COMPLETED,
                or_(*trip_filters),
            )
            .order_by(FieldTrip.departure_at)
        )
        for other in others:
            if _windows_overlap(windows, trip_windows(other)):
                blocking.append(
                    f"Field trip #{other.id} to {other.destination} "
                    f"({other.departure_at.strftime('%Y-%m-%d %H:%M')}-"
                    f"{trip_return(other).strftime('%Y-%m-%d %H:%M')}) overlaps this trip"
                )
    for day, start, end in windows:
        for task in tasks_blocking(db, day, driver_id=driver_id, vehicle_id=vehicle_id):
            if start < task.end_minute and task.start_minute < end:
                blocking.append(
                    f"Dispatch task #{task.id} ({task.kind.value.replace('_', ' ')}, {day} "
                    f"{_hhmm(task.start_minute)}-{_hhmm(task.end_minute)}) overlaps this trip"
                )
    return blocking, route_overlaps


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
    12.2's delay-management reevaluation."""
    trip = db.get(FieldTrip, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field trip not found")
    driver_id = driver_id if driver_id is not None else trip.assigned_driver_id
    vehicle_id = vehicle_id if vehicle_id is not None else trip.assigned_vehicle_id
    blocking, route_overlaps = _trip_conflicts(db, trip, driver_id, vehicle_id)
    return FieldTripConflictCheck(
        conflicts=blocking + route_overlaps,
        routes_needing_cover=route_overlaps,
        turnaround_minutes=FIELD_TRIP_TURNAROUND_MINUTES,
    )
