"""Fleet maintenance (spec sections 2.1, 9, 12.1, 19).

Decided by the product owner on 2026-10-15:
- A bus goes out of service in maintenance windows (planned or
  unplanned; whole days or part of one; open-ended until marked back in
  service). The scheduler, template generation and field-trip checks
  treat the bus as busy then (isd_api/availability.py).
- Each bus has a next-service-due date and an inspection expiry date, and
  a service log. Dispatch is warned `DUE_WARNING_DAYS` ahead; after its
  inspection expires a bus isn't scheduled.
- A driver's vehicle defect report is tracked to resolution: open, then
  the bus taken out of service (which opens a maintenance window), then
  fixed (which closes it).
- When a bus is lost while it already has work, dispatch is offered spare
  buses that fit the crew's runs and swaps one in; the driver keeps
  their runs.

Times are wall-clock in the district's time zone, like field trips.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from isd_api import ridership_rules
from isd_api.availability import tasks_blocking, trips_blocking, vehicle_conflict_for_window
from isd_api.licensing import license_violation
from isd_api.models import Assignment, Crew, MaintenanceWindow, Vehicle
from isd_api.routes import expected_demand, wheelchair_demand

DUE_WARNING_DAYS = 14


def district_now(db: Session) -> datetime:
    """Now on the district's wall clock, without a time zone (like the windows)."""
    rules = ridership_rules.load_rules(db)
    return ridership_rules.district_now(rules).replace(tzinfo=None, second=0, microsecond=0)


def due_notes(vehicle: Vehicle, today: date) -> list[tuple[str, str]]:
    """(severity, message) for service or inspection due soon or past."""
    notes: list[tuple[str, str]] = []
    if vehicle.inspection_expires_on is not None:
        left = (vehicle.inspection_expires_on - today).days
        if left < 0:
            notes.append(
                (
                    "critical",
                    f"{vehicle.label}'s inspection expired on {vehicle.inspection_expires_on}; "
                    "it isn't scheduled until it's renewed",
                )
            )
        elif left <= DUE_WARNING_DAYS:
            notes.append(
                (
                    "warning",
                    f"{vehicle.label}'s inspection expires on {vehicle.inspection_expires_on}",
                )
            )
    if vehicle.service_due_on is not None:
        left = (vehicle.service_due_on - today).days
        if left < 0:
            notes.append(
                ("warning", f"{vehicle.label}'s service was due on {vehicle.service_due_on}")
            )
        elif left <= DUE_WARNING_DAYS:
            notes.append(
                ("warning", f"{vehicle.label}'s service is due on {vehicle.service_due_on}")
            )
    return notes


def open_window(db: Session, vehicle_id: int) -> MaintenanceWindow | None:
    """The bus's maintenance window in effect now, if any."""
    now = district_now(db)
    return (
        db.query(MaintenanceWindow)
        .filter(
            MaintenanceWindow.vehicle_id == vehicle_id,
            MaintenanceWindow.starts_at <= now,
            (MaintenanceWindow.ends_at.is_(None)) | (MaintenanceWindow.ends_at > now),
        )
        .order_by(MaintenanceWindow.starts_at)
        .first()
    )


@dataclass(frozen=True)
class Spare:
    vehicle: Vehicle
    # Its allowable capacity minus the most riders any of the crew's runs expects.
    spare_seats: int | None


def spare_vehicles(db: Session, crew: Crew) -> list[Spare]:
    """Buses that could take over all of `crew`'s work that day: in
    service, not already crewed that day, free for every one of the
    crew's assignments, big enough, with the capabilities the runs need,
    and a bus the crew's driver is licensed for. Smallest fit first."""
    assignments = db.query(Assignment).filter(Assignment.crew_id == crew.id).all()
    taken = {
        vid for (vid,) in db.query(Crew.vehicle_id).filter(Crew.service_date == crew.service_date)
    }
    riders = max((expected_demand(db, a.run) for a in assignments), default=0)
    chairs = max((wheelchair_demand(db, a.run) for a in assignments), default=0)
    needed = {q.code for a in assignments for q in a.run.required_qualifications}
    spares: list[Spare] = []
    for vehicle in db.query(Vehicle).filter(Vehicle.is_active.is_(True)).order_by(Vehicle.label):
        if vehicle.id in taken:
            continue
        if license_violation(crew.driver, vehicle) is not None:
            continue
        if not needed <= {q.code for q in vehicle.qualifications}:
            continue
        capacity = vehicle.allowable_capacity()
        # Unknown capacity fails closed, as in the scheduler.
        if riders > 0 and (capacity is None or capacity < riders):
            continue
        positions = vehicle.wheelchair_positions
        if chairs > 0 and (positions is None or positions < chairs):
            continue
        if any(
            vehicle_conflict_for_window(
                db, vehicle, crew.service_date, a.start_minute, a.end_minute
            )
            is not None
            for a in assignments
        ):
            continue
        busy = [
            (start, end)
            for _, start, end in trips_blocking(db, crew.service_date, vehicle_id=vehicle.id)
        ] + [
            (t.start_minute, t.end_minute)
            for t in tasks_blocking(db, crew.service_date, vehicle_id=vehicle.id)
        ]
        if any(
            a.start_minute < end and start < a.end_minute
            for a in assignments
            for start, end in busy
        ):
            continue
        spares.append(Spare(vehicle, capacity - riders if capacity is not None else None))
    spares.sort(key=lambda s: (s.spare_seats is None, s.spare_seats or 0, s.vehicle.label))
    return spares
