"""Driver and vehicle availability as a scheduling constraint (spec
sections 2.1, 5, 13): one place that decides whether a crew can take
work at a given time, so the solver, manual reassignment, crew creation,
template generation, and substitute ranking can't disagree.

Three things make a crew unavailable:
  - its vehicle is out of service (``Vehicle.is_active`` false),
  - its driver is deactivated (``Driver.is_active`` false),
  - a recorded ``DriverAbsence`` for that driver and date. A partial-day
    absence only blocks the minutes it covers; one covering the crew's
    whole available window blocks the whole crew.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from isd_api.models import Assignment, Crew, Driver, DriverAbsence, Vehicle


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


def resource_unavailable_reason(driver: Driver, vehicle: Vehicle) -> str | None:
    """Out-of-service or deactivated resources: never schedulable."""
    if not vehicle.is_active:
        return f"vehicle {vehicle.label} is out of service"
    if not driver.is_active:
        return f"driver {driver.full_name} is deactivated"
    return None


def driver_absences(db: Session, driver_id: int, service_date: date) -> list[DriverAbsence]:
    return (
        db.query(DriverAbsence)
        .filter(DriverAbsence.driver_id == driver_id, DriverAbsence.service_date == service_date)
        .order_by(DriverAbsence.start_minute)
        .all()
    )


def crew_availability(db: Session, crew: Crew) -> CrewAvailability:
    reason = resource_unavailable_reason(crew.driver, crew.vehicle)
    if reason is not None:
        return CrewAvailability(unavailable_reason=reason)

    earliest, latest = crew.available_window_earliest, crew.available_window_latest
    busy: list[BusyWindow] = []
    for absence in driver_absences(db, crew.driver_id, crew.service_date):
        if absence.start_minute <= earliest and absence.end_minute >= latest:
            return CrewAvailability(unavailable_reason=_absence_label(absence))
        start, end = max(absence.start_minute, earliest), min(absence.end_minute, latest)
        if start < end:
            busy.append(BusyWindow(start, end, _absence_label(absence)))
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
    ranking): deactivated, or absent during any part of the window."""
    if not driver.is_active:
        return f"driver {driver.full_name} is deactivated"
    for absence in driver_absences(db, driver.id, service_date):
        if start_minute < absence.end_minute and absence.start_minute < end_minute:
            return _absence_label(absence)
    return None


def assignment_availability_issue(db: Session, assignment: Assignment) -> str | None:
    """For flagging an existing assignment whose crew became unavailable
    after it was made (a new absence, a bus taken out of service)."""
    return conflict_for_window(db, assignment.crew, assignment.start_minute, assignment.end_minute)
