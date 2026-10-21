"""Driver and vehicle availability as a scheduling constraint (spec
sections 2.1, 5, 13): one place that decides whether a crew can take
work at a given time, so the solver, manual reassignment, crew creation,
template generation, and substitute ranking can't disagree.

Five things make a crew unavailable:
  - its vehicle is out of service (``Vehicle.is_active`` false),
  - its driver is deactivated (``Driver.is_active`` false),
  - a recorded ``DriverAbsence`` for that driver and date,
  - a field trip assigned to that driver or that vehicle (spec section 12:
    trips are jobs in the same scheduling engine), padded by
    ``FIELD_TRIP_TURNAROUND_MINUTES`` on each side,
  - a dispatch task (spec section 14's unplanned work) for that driver or
    that vehicle, unless it was cancelled. Not padded: dispatch sets the
    window it needs,
  - its vehicle in a maintenance window (spec section 12.1 "Maintenance"),
    or past its inspection's expiry date (isd_api/maintenance.py).
A block that covers only part of the crew's available window is busy
time; one covering the whole window makes the crew unavailable all day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from isd_solver import Location as SolverLocation
from isd_solver import Vehicle as SolverVehicle
from isd_solver import straight_line_deadhead_estimator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from isd_api.licensing import license_violation
from isd_api.models import (
    Assignment,
    Crew,
    DispatchTask,
    Driver,
    DriverAbsence,
    FieldTrip,
    MaintenanceWindow,
    Run,
    School,
    Vehicle,
)

# Time a field trip's driver and bus are held before departure and after
# return: pre-/post-trip inspection and travel between the yard and the
# trip (spec sections 12.1 "travel time between assignments", 16
# "pre-trip/post-trip procedures"). One district-wide default for now.
FIELD_TRIP_TURNAROUND_MINUTES = 15


@dataclass(frozen=True)
class BusyWindow:
    start_minute: int
    end_minute: int
    reason: str


@dataclass(frozen=True)
class CrewAvailability:
    # Set when the crew can't take any work at all that day.
    unavailable_reason: str | None
    # Partial-day blocks, clipped to the crew's available window.
    busy_windows: list[BusyWindow] = field(default_factory=list)


def _absence_label(absence: DriverAbsence) -> str:
    return (
        f"driver absent ({absence.reason.value.replace('_', ' ')}, "
        f"{_hhmm(absence.start_minute)}-{_hhmm(absence.end_minute)})"
    )


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def daily_windows(start: datetime, end: datetime) -> list[tuple[date, int, int]]:
    """Splits `[start, end)` into one (date, start_minute, end_minute)
    window per calendar day it touches; a day strictly between the first
    and last spans the whole day. Timestamps are wall-clock (naive)."""
    start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
    windows: list[tuple[date, int, int]] = []
    current_date = start.date()
    while current_date <= end.date():
        day_start = _minute_of_day(start) if current_date == start.date() else 0
        day_end = _minute_of_day(end) if current_date == end.date() else 1439
        windows.append((current_date, day_start, day_end))
        current_date += timedelta(days=1)
    return windows


def trip_return(trip: FieldTrip) -> datetime:
    """The trip's actual return once recorded, else the expected one."""
    return trip.actual_return_at or trip.expected_return_at


def trip_windows(trip: FieldTrip, *, padded: bool = True) -> list[tuple[date, int, int]]:
    pad = timedelta(minutes=FIELD_TRIP_TURNAROUND_MINUTES if padded else 0)
    return daily_windows(trip.departure_at - pad, trip_return(trip) + pad)


_TRAVEL = straight_line_deadhead_estimator()
_ANY_BUS = SolverVehicle(id="any")


def travel_pad(db: Session, trip: FieldTrip, service_date: date) -> int:
    """Spec section 12.1: time to drive between the trip's school and the
    farthest school with runs that day, held on each side of the trip so
    the bus can get from one to the other. 0 when the trip doesn't start
    from one of our schools (its origin is just words then). Conservative:
    the same for every run that day, so a nearer school gets slack."""
    origin = trip.origin_school
    if origin is None:
        return 0
    start = SolverLocation(lat=origin.location_lat, lon=origin.location_lon)
    # Distinct ids first: PostgreSQL can't DISTINCT whole School rows, since
    # they hold a JSON column (the attendance zone).
    with_runs = (
        db.query(Run.school_id)
        .filter(Run.service_date == service_date, Run.school_id != origin.id)
        .distinct()
    )
    schools = db.query(School).filter(School.id.in_(with_runs)).all()
    return max(
        (
            _TRAVEL(start, SolverLocation(lat=s.location_lat, lon=s.location_lon), _ANY_BUS)
            for s in schools
        ),
        default=0,
    )


def trip_day_windows(
    db: Session, trip: FieldTrip, windows: list[tuple[date, int, int]] | None = None
) -> list[tuple[date, int, int]]:
    """The trip's padded windows, widened by `travel_pad` on each day."""
    days = windows if windows is not None else trip_windows(trip)
    widened = []
    for day, start, end in days:
        pad = travel_pad(db, trip, day)
        widened.append((day, max(0, start - pad), min(24 * 60 - 1, end + pad)))
    return widened


def _trip_label(trip: FieldTrip) -> str:
    return (
        f"on field trip #{trip.id} to {trip.destination} "
        f"({trip.departure_at.strftime('%H:%M')}-{trip_return(trip).strftime('%H:%M')})"
    )


def trips_blocking(
    db: Session,
    service_date: date,
    *,
    driver_id: int | None = None,
    vehicle_id: int | None = None,
    exclude_trip_id: int | None = None,
) -> list[tuple[FieldTrip, int, int]]:
    """Field trips holding this driver or vehicle on `service_date`, each
    with its padded (start_minute, end_minute) on that day."""
    matches = []
    if driver_id is not None:
        matches.append(FieldTrip.assigned_driver_id == driver_id)
    if vehicle_id is not None:
        matches.append(FieldTrip.assigned_vehicle_id == vehicle_id)
    if not matches:
        return []
    query = db.query(FieldTrip).filter(or_(*matches))
    if exclude_trip_id is not None:
        query = query.filter(FieldTrip.id != exclude_trip_id)
    blocking = []
    for trip in query.order_by(FieldTrip.id):
        for day, start, end in trip_day_windows(db, trip):
            if day == service_date:
                blocking.append((trip, start, end))
    return blocking


def task_label(task: DispatchTask) -> str:
    return (
        f"on dispatch task #{task.id} ({task.kind.value.replace('_', ' ')}, "
        f"{_hhmm(task.start_minute)}-{_hhmm(task.end_minute)})"
    )


def tasks_blocking(
    db: Session,
    service_date: date,
    *,
    driver_id: int | None = None,
    vehicle_id: int | None = None,
    exclude_task_id: int | None = None,
) -> list[DispatchTask]:
    """Uncancelled dispatch tasks holding this driver or vehicle on
    `service_date`."""
    matches = []
    if driver_id is not None:
        matches.append(DispatchTask.driver_id == driver_id)
    if vehicle_id is not None:
        matches.append(DispatchTask.vehicle_id == vehicle_id)
    if not matches:
        return []
    query = db.query(DispatchTask).filter(
        DispatchTask.service_date == service_date,
        DispatchTask.cancelled_at.is_(None),
        or_(*matches),
    )
    if exclude_task_id is not None:
        query = query.filter(DispatchTask.id != exclude_task_id)
    return query.order_by(DispatchTask.start_minute, DispatchTask.id).all()


def resource_unavailable_reason(driver: Driver, vehicle: Vehicle) -> str | None:
    """Out-of-service or deactivated resources: never schedulable."""
    if not vehicle.is_active:
        return f"vehicle {vehicle.label} is out of service"
    if not driver.is_active:
        return f"driver {driver.full_name} is deactivated"
    return None


def _maintenance_label(vehicle: Vehicle, window: MaintenanceWindow) -> str:
    until = window.ends_at.strftime("%Y-%m-%d %H:%M") if window.ends_at else "fixed"
    return f"bus {vehicle.label} in maintenance ({window.reason}, until {until})"


def vehicle_blocks(db: Session, vehicle: Vehicle, service_date: date) -> list[tuple[int, int, str]]:
    """Times on `service_date` a bus can't run for maintenance: its
    maintenance windows, and the whole day once its inspection has expired."""
    blocks: list[tuple[int, int, str]] = []
    if vehicle.inspection_expires_on is not None and service_date > vehicle.inspection_expires_on:
        blocks.append(
            (
                0,
                1439,
                f"bus {vehicle.label}'s inspection expired on {vehicle.inspection_expires_on}",
            )
        )
    day_start = datetime.combine(service_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    windows = (
        db.query(MaintenanceWindow)
        .filter(
            MaintenanceWindow.vehicle_id == vehicle.id,
            MaintenanceWindow.starts_at < day_end,
            or_(MaintenanceWindow.ends_at.is_(None), MaintenanceWindow.ends_at > day_start),
        )
        .order_by(MaintenanceWindow.starts_at)
    )
    for window in windows:
        start = _minute_of_day(window.starts_at) if window.starts_at >= day_start else 0
        ends_today = window.ends_at is not None and window.ends_at < day_end
        end = _minute_of_day(window.ends_at) if ends_today and window.ends_at else 1439
        blocks.append((start, end, _maintenance_label(vehicle, window)))
    return blocks


def vehicle_conflict_for_window(
    db: Session, vehicle: Vehicle, service_date: date, start_minute: int, end_minute: int
) -> str | None:
    """Why this bus can't run during [start_minute, end_minute] for
    reasons of its own (out of service, maintenance, inspection), or None."""
    if not vehicle.is_active:
        return f"vehicle {vehicle.label} is out of service"
    for start, end, label in vehicle_blocks(db, vehicle, service_date):
        if start_minute < end and start < end_minute:
            return label
    return None


def driver_absences(db: Session, driver_id: int, service_date: date) -> list[DriverAbsence]:
    return (
        db.query(DriverAbsence)
        .filter(DriverAbsence.driver_id == driver_id, DriverAbsence.service_date == service_date)
        .order_by(DriverAbsence.start_minute)
        .all()
    )


def pairing_problem(driver: Driver, vehicle: Vehicle) -> str | None:
    """Why this driver can't work this vehicle at all: out of service,
    deactivated, or not licensed for it (spec sections 2.1, 15)."""
    return resource_unavailable_reason(driver, vehicle) or license_violation(driver, vehicle)


def crew_availability(db: Session, crew: Crew) -> CrewAvailability:
    reason = pairing_problem(crew.driver, crew.vehicle)
    if reason is not None:
        return CrewAvailability(unavailable_reason=reason)

    blocks = (
        [
            (a.start_minute, a.end_minute, _absence_label(a))
            for a in driver_absences(db, crew.driver_id, crew.service_date)
        ]
        + [
            (start, end, _trip_label(trip))
            for trip, start, end in trips_blocking(
                db, crew.service_date, driver_id=crew.driver_id, vehicle_id=crew.vehicle_id
            )
        ]
        + [
            (task.start_minute, task.end_minute, task_label(task))
            for task in tasks_blocking(
                db, crew.service_date, driver_id=crew.driver_id, vehicle_id=crew.vehicle_id
            )
        ]
        + vehicle_blocks(db, crew.vehicle, crew.service_date)
    )
    earliest, latest = crew.available_window_earliest, crew.available_window_latest
    busy: list[BusyWindow] = []
    for block_start, block_end, label in blocks:
        if block_start <= earliest and block_end >= latest:
            return CrewAvailability(unavailable_reason=label)
        start, end = max(block_start, earliest), min(block_end, latest)
        if start < end:
            busy.append(BusyWindow(start, end, label))
    busy.sort(key=lambda w: w.start_minute)
    return CrewAvailability(unavailable_reason=None, busy_windows=busy)


def conflict_for_window(db: Session, crew: Crew, start_minute: int, end_minute: int) -> str | None:
    """Why this crew can't work [start_minute, end_minute], or None."""
    availability = crew_availability(db, crew)
    if availability.unavailable_reason is not None:
        return availability.unavailable_reason
    for window in availability.busy_windows:
        if start_minute < window.end_minute and window.start_minute < end_minute:
            return window.reason
    return None


def driver_conflict_for_window(
    db: Session, driver: Driver, service_date: date, start_minute: int, end_minute: int
) -> str | None:
    """The same rule for a driver without a crew yet (substitute
    ranking): deactivated, absent, on a field trip or on a dispatch task
    during any part of the window."""
    if not driver.is_active:
        return f"driver {driver.full_name} is deactivated"
    for absence in driver_absences(db, driver.id, service_date):
        if start_minute < absence.end_minute and absence.start_minute < end_minute:
            return _absence_label(absence)
    for trip, trip_start, trip_end in trips_blocking(db, service_date, driver_id=driver.id):
        if start_minute < trip_end and trip_start < end_minute:
            return _trip_label(trip)
    for task in tasks_blocking(db, service_date, driver_id=driver.id):
        if start_minute < task.end_minute and task.start_minute < end_minute:
            return task_label(task)
    return None


def assignment_availability_issue(db: Session, assignment: Assignment) -> str | None:
    """For flagging an existing assignment whose crew became unavailable
    after it was made (a new absence, a bus taken out of service)."""
    return conflict_for_window(db, assignment.crew, assignment.start_minute, assignment.end_minute)
