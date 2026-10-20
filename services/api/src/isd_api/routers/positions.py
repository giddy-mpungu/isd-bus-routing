"""spec section 9 (real-time navigation) and section 17 (dispatcher's
"GPS fleet view"). ADR 0009: position comes from the driver's own
tablet (browser Geolocation API), not a dedicated GPS/AVL vendor.
`VehiclePosition` holds the latest position for the live view; since
PR #55 every report is also kept as history for a limited time
(`isd_api/position_history.py`, ADR 0009's addendum). The family-facing read
(spec section 18) lives in routers/students.py instead, since it needs
the same guardian/self RBAC helper that file already has."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api import tracking
from isd_api.db import get_db
from isd_api.models import Crew, Driver, Role, User, VehiclePosition
from isd_api.position_history import record_sample, track
from isd_api.schemas import PositionSampleRead, PositionUpdate, VehiclePositionRead
from isd_api.security import get_current_user, require_role

# A driver reporting their own position, alongside the existing
# /drivers/{id}/absences self-report endpoint (routers/absences.py).
driver_router = APIRouter(prefix="/drivers", tags=["positions"])
# The dispatcher fleet view, alongside the existing /schedule/{date}/...
# family of endpoints (routers/schedule.py).
fleet_router = APIRouter(prefix="/schedule", tags=["positions"])

_FLEET_READ_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


@driver_router.put("/{driver_id}/position", status_code=status.HTTP_204_NO_CONTENT)
def report_position(
    driver_id: int,
    payload: PositionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Only the driver themself reports their own position -- unlike
    absences (which staff can also report on a driver's behalf via a
    phone call), there's no legitimate case for anyone else to submit
    a device's GPS reading, so no is_staff bypass here."""
    if current_user.role != Role.DRIVER or current_user.driver_id != driver_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only report your own vehicle's position",
        )
    if db.get(Driver, driver_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    crew = (
        db.query(Crew)
        .filter(Crew.driver_id == driver_id, Crew.service_date == payload.service_date)
        .one_or_none()
    )
    if crew is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You have no crew assignment for that service_date",
        )

    position = db.query(VehiclePosition).filter(VehiclePosition.crew_id == crew.id).one_or_none()
    if position is None:
        db.add(
            VehiclePosition(
                crew_id=crew.id,
                location_lat=payload.location_lat,
                location_lon=payload.location_lon,
                recorded_at=payload.recorded_at,
            )
        )
    else:
        position.location_lat = payload.location_lat
        position.location_lon = payload.location_lon
        position.recorded_at = payload.recorded_at
    record_sample(db, crew, payload.location_lat, payload.location_lon, payload.recorded_at)
    # Deliberately not audit-logged (isd_api.audit): these pings are
    # expected every 15-30s while a run is active (ADR 0009), and the
    # append-only audit trail (spec section 14) is meant for material,
    # human-reviewable changes -- logging every GPS tick would drown
    # that signal, not add to it.
    db.commit()


@fleet_router.get("/{service_date}/fleet-positions", response_model=list[VehiclePositionRead])
def list_fleet_positions(
    service_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_FLEET_READ_ROLES)),
) -> list[VehiclePositionRead]:
    rows = (
        db.query(VehiclePosition)
        .join(Crew, VehiclePosition.crew_id == Crew.id)
        .filter(Crew.service_date == service_date)
        .all()
    )
    reads = []
    for p in rows:
        going = tracking.heading(db, p.crew_id)
        reads.append(
            VehiclePositionRead(
                crew_id=p.crew_id,
                driver_id=p.crew.driver_id,
                driver_full_name=p.crew.driver.full_name,
                vehicle_id=p.crew.vehicle_id,
                vehicle_label=p.crew.vehicle.label,
                location_lat=p.location_lat,
                location_lon=p.location_lon,
                recorded_at=p.recorded_at,
                heading_degrees=None if going is None else round(going),
                heading=None if going is None else tracking.compass(going),
            )
        )
    return reads


@fleet_router.get(
    "/{service_date}/fleet-positions/{crew_id}/track", response_model=list[PositionSampleRead]
)
def get_crew_track(
    service_date: date,
    crew_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_FLEET_READ_ROLES)),
) -> list[PositionSampleRead]:
    """A crew's reported positions for the day, oldest first (spec section
    9 "route progress"; the fleet map draws it as a line)."""
    crew = db.get(Crew, crew_id)
    if crew is None or crew.service_date != service_date:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    return [
        PositionSampleRead(
            location_lat=s.location_lat, location_lon=s.location_lon, recorded_at=s.recorded_at
        )
        for s in track(db, crew_id)
    ]
