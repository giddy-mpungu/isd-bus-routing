"""spec section 9: the driver app's "Incident reporting" and "Vehicle
defect reporting" -- one DriverReport entity with a type discriminator,
same shape as absences.py's DriverAbsence router."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Crew, Driver, DriverReport, Role, User
from isd_api.schemas import DriverReportCreate, DriverReportRead
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/drivers", tags=["driver-reports"])
# Driver-agnostic listing ("what's been reported today") doesn't fit
# the /drivers prefix above -- a separate router, same split as
# absences.py's all_absences_router.
all_reports_router = APIRouter(prefix="/reports", tags=["driver-reports"])


@router.post(
    "/{driver_id}/reports", response_model=DriverReportRead, status_code=status.HTTP_201_CREATED
)
def create_driver_report(
    driver_id: int,
    payload: DriverReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DriverReport:
    """A driver reports their own incident/defect, or transportation_admin/
    dispatcher files one on a driver's behalf (e.g. a phone call) --
    same RBAC shape as absences.py's create_absence."""
    is_self = current_user.role == Role.DRIVER and current_user.driver_id == driver_id
    is_staff = current_user.role in (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)
    if not (is_self or is_staff):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only file your own report",
        )
    if db.get(Driver, driver_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    # The vehicle they were actually driving, not driver-supplied --
    # see DriverReport's docstring.
    crew = (
        db.query(Crew)
        .filter(Crew.driver_id == driver_id, Crew.service_date == payload.service_date)
        .one_or_none()
    )
    report = DriverReport(
        driver_id=driver_id,
        vehicle_id=crew.vehicle_id if crew is not None else None,
        service_date=payload.service_date,
        report_type=payload.report_type,
        description=payload.description,
    )
    db.add(report)
    db.flush()
    record_audit(
        db,
        entity_type="driver_report",
        entity_id=report.id,
        action="created",
        actor=current_user,
        after_state={
            "driver_id": driver_id,
            "service_date": str(payload.service_date),
            "report_type": payload.report_type.value,
        },
    )
    db.commit()
    db.refresh(report)
    return report


@all_reports_router.get("", response_model=list[DriverReportRead])
def list_driver_reports(
    service_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[DriverReport]:
    return list(
        db.query(DriverReport)
        .filter(DriverReport.service_date == service_date)
        .order_by(DriverReport.id)
        .all()
    )
