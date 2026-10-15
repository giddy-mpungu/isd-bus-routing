"""Fleet maintenance (isd_api/maintenance.py has the decisions): maintenance
windows, service and inspection dates with a service log, vehicle defect
reports tracked to resolution, and swapping a spare bus onto a crew.

Transportation administrators and dispatchers use all of it: it's day-to-
day operations, like absences and field trips. Every change is audited."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from isd_api import maintenance
from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import (
    Assignment,
    Crew,
    DefectStatus,
    DriverReport,
    DriverReportType,
    MaintenanceKind,
    MaintenanceWindow,
    Role,
    ServiceRecord,
    User,
    Vehicle,
)
from isd_api.schemas import (
    CrewRead,
    CrewVehicleUpdate,
    DefectFixed,
    DefectOutOfService,
    DefectReportRead,
    MaintenanceDueRead,
    MaintenanceWindowCreate,
    MaintenanceWindowRead,
    ServiceRecordCreate,
    ServiceRecordRead,
    SparesRead,
    SpareVehicleRead,
    VehicleMaintenanceDates,
    VehicleMaintenanceRead,
)
from isd_api.security import require_role

router = APIRouter(tags=["maintenance"])

_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


def _vehicle(db: Session, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")
    return vehicle


def _window_read(db: Session, window: MaintenanceWindow) -> MaintenanceWindowRead:
    now = maintenance.district_now(db)
    return MaintenanceWindowRead(
        id=window.id,
        vehicle_id=window.vehicle_id,
        vehicle_label=window.vehicle.label,
        kind=window.kind,
        starts_at=window.starts_at,
        ends_at=window.ends_at,
        reason=window.reason,
        driver_report_id=window.driver_report_id,
        current=window.starts_at <= now and (window.ends_at is None or window.ends_at > now),
    )


def _defect_read(report: DriverReport) -> DefectReportRead:
    return DefectReportRead(
        id=report.id,
        driver_id=report.driver_id,
        vehicle_id=report.vehicle_id,
        service_date=report.service_date,
        report_type=report.report_type,
        description=report.description,
        created_at=report.created_at,
        status=report.status,
        resolution_note=report.resolution_note,
        driver_name=report.driver.full_name,
        vehicle_label=report.vehicle.label if report.vehicle is not None else None,
    )


def _wall(moment: datetime) -> datetime:
    """Wall-clock times: an offset sent by a client is dropped, not converted."""
    return moment.replace(tzinfo=None, second=0, microsecond=0)


# --- Maintenance windows ---------------------------------------------------


@router.get("/maintenance/windows", response_model=list[MaintenanceWindowRead])
def list_windows(
    include_past: bool = Query(default=False),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_ROLES)),
) -> list[MaintenanceWindowRead]:
    """Windows going on now or still to come (all of them with include_past)."""
    query = db.query(MaintenanceWindow)
    if not include_past:
        now = maintenance.district_now(db)
        query = query.filter(
            (MaintenanceWindow.ends_at.is_(None)) | (MaintenanceWindow.ends_at > now)
        )
    windows = query.order_by(MaintenanceWindow.starts_at, MaintenanceWindow.id).all()
    return [_window_read(db, w) for w in windows]


@router.post(
    "/maintenance/windows",
    response_model=MaintenanceWindowRead,
    status_code=status.HTTP_201_CREATED,
)
def create_window(
    payload: MaintenanceWindowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> MaintenanceWindowRead:
    vehicle = _vehicle(db, payload.vehicle_id)
    window = MaintenanceWindow(
        vehicle_id=vehicle.id,
        kind=payload.kind,
        starts_at=_wall(payload.starts_at),
        ends_at=_wall(payload.ends_at) if payload.ends_at is not None else None,
        reason=payload.reason.strip(),
        created_by_user_id=current_user.id,
    )
    db.add(window)
    db.flush()
    record_audit(
        db,
        entity_type="vehicle",
        entity_id=vehicle.id,
        action="maintenance_window_created",
        actor=current_user,
        after_state={
            "window_id": window.id,
            "kind": window.kind.value,
            "starts_at": window.starts_at.isoformat(),
            "ends_at": window.ends_at.isoformat() if window.ends_at else None,
            "reason": window.reason,
        },
    )
    db.commit()
    db.refresh(window)
    return _window_read(db, window)


def _end_window(db: Session, window: MaintenanceWindow, actor: User) -> None:
    """Ends a window now; one that hasn't started yet is simply removed."""
    now = maintenance.district_now(db)
    before = {
        "window_id": window.id,
        "ends_at": window.ends_at.isoformat() if window.ends_at else None,
    }
    if window.starts_at > now:
        record_audit(
            db,
            entity_type="vehicle",
            entity_id=window.vehicle_id,
            action="maintenance_window_cancelled",
            actor=actor,
            before_state=before,
        )
        db.delete(window)
        return
    window.ends_at = now
    record_audit(
        db,
        entity_type="vehicle",
        entity_id=window.vehicle_id,
        action="back_in_service",
        actor=actor,
        before_state=before,
        after_state={"window_id": window.id, "ends_at": now.isoformat()},
    )


@router.post("/maintenance/windows/{window_id}/end", status_code=status.HTTP_204_NO_CONTENT)
def end_window(
    window_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> None:
    """Back in service now (or, for a window still to come, cancelled). A
    window opened from a defect report marks the report fixed."""
    window = db.get(MaintenanceWindow, window_id)
    if window is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Maintenance window not found"
        )
    now = maintenance.district_now(db)
    if window.ends_at is not None and window.ends_at <= now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That window is over")
    report = db.get(DriverReport, window.driver_report_id) if window.driver_report_id else None
    _end_window(db, window, current_user)
    if report is not None and report.status == DefectStatus.OUT_OF_SERVICE:
        _mark_fixed(report, "Back in service", current_user)
    db.commit()


# --- Service and inspection dates, service log ------------------------------


def _vehicle_maintenance(db: Session, vehicle: Vehicle) -> VehicleMaintenanceRead:
    records = (
        db.query(ServiceRecord)
        .filter(ServiceRecord.vehicle_id == vehicle.id)
        .order_by(ServiceRecord.performed_on.desc(), ServiceRecord.id.desc())
        .all()
    )
    windows = (
        db.query(MaintenanceWindow)
        .filter(MaintenanceWindow.vehicle_id == vehicle.id)
        .order_by(MaintenanceWindow.starts_at.desc())
        .limit(20)
        .all()
    )
    return VehicleMaintenanceRead(
        vehicle_id=vehicle.id,
        vehicle_label=vehicle.label,
        service_due_on=vehicle.service_due_on,
        inspection_expires_on=vehicle.inspection_expires_on,
        service_log=[ServiceRecordRead.model_validate(r) for r in records],
        windows=[_window_read(db, w) for w in windows],
    )


@router.get("/vehicles/{vehicle_id}/maintenance", response_model=VehicleMaintenanceRead)
def get_vehicle_maintenance(
    vehicle_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_ROLES)),
) -> VehicleMaintenanceRead:
    return _vehicle_maintenance(db, _vehicle(db, vehicle_id))


@router.put("/vehicles/{vehicle_id}/maintenance-dates", response_model=VehicleMaintenanceRead)
def put_maintenance_dates(
    vehicle_id: int,
    payload: VehicleMaintenanceDates,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> VehicleMaintenanceRead:
    vehicle = _vehicle(db, vehicle_id)
    before = {
        "service_due_on": str(vehicle.service_due_on) if vehicle.service_due_on else None,
        "inspection_expires_on": (
            str(vehicle.inspection_expires_on) if vehicle.inspection_expires_on else None
        ),
    }
    vehicle.service_due_on = payload.service_due_on
    vehicle.inspection_expires_on = payload.inspection_expires_on
    record_audit(
        db,
        entity_type="vehicle",
        entity_id=vehicle.id,
        action="maintenance_dates_updated",
        actor=current_user,
        before_state=before,
        after_state=payload.model_dump(mode="json"),
    )
    db.commit()
    return _vehicle_maintenance(db, vehicle)


@router.post(
    "/vehicles/{vehicle_id}/service-records",
    response_model=VehicleMaintenanceRead,
    status_code=status.HTTP_201_CREATED,
)
def add_service_record(
    vehicle_id: int,
    payload: ServiceRecordCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> VehicleMaintenanceRead:
    vehicle = _vehicle(db, vehicle_id)
    record = ServiceRecord(
        vehicle_id=vehicle.id,
        performed_on=payload.performed_on,
        work=payload.work.strip(),
        performed_by=payload.performed_by.strip(),
        recorded_by_user_id=current_user.id,
    )
    db.add(record)
    if payload.next_service_due_on is not None:
        vehicle.service_due_on = payload.next_service_due_on
    if payload.inspection_expires_on is not None:
        vehicle.inspection_expires_on = payload.inspection_expires_on
    db.flush()
    record_audit(
        db,
        entity_type="vehicle",
        entity_id=vehicle.id,
        action="service_recorded",
        actor=current_user,
        after_state=payload.model_dump(mode="json") | {"record_id": record.id},
    )
    db.commit()
    return _vehicle_maintenance(db, vehicle)


@router.get("/maintenance/due", response_model=list[MaintenanceDueRead])
def list_due(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_ROLES)),
) -> list[MaintenanceDueRead]:
    """In-service buses whose service or inspection is due soon or past."""
    today = maintenance.district_now(db).date()
    due = []
    for vehicle in db.query(Vehicle).filter(Vehicle.is_active.is_(True)).order_by(Vehicle.label):
        for severity, message in maintenance.due_notes(vehicle, today):
            due.append(
                MaintenanceDueRead(
                    vehicle_id=vehicle.id,
                    vehicle_label=vehicle.label,
                    severity=severity,
                    message=message,
                )
            )
    return due


# --- Defect reports ---------------------------------------------------------


def _defect(db: Session, report_id: int) -> DriverReport:
    report = db.get(DriverReport, report_id)
    if report is None or report.report_type != DriverReportType.VEHICLE_DEFECT:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Defect report not found")
    return report


def _mark_fixed(report: DriverReport, note: str, actor: User) -> None:
    report.status = DefectStatus.FIXED
    report.resolved_at = datetime.now(UTC)
    report.resolved_by_user_id = actor.id
    report.resolution_note = note or None


@router.get("/maintenance/defects", response_model=list[DefectReportRead])
def list_defects(
    status_filter: str = Query(default="open", pattern="^(open|active|all)$"),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_ROLES)),
) -> list[DefectReportRead]:
    """open: not dealt with yet; active: open or the bus is out for it; all."""
    query = db.query(DriverReport).filter(
        DriverReport.report_type == DriverReportType.VEHICLE_DEFECT
    )
    if status_filter == "open":
        query = query.filter(DriverReport.status == DefectStatus.OPEN)
    elif status_filter == "active":
        query = query.filter(DriverReport.status != DefectStatus.FIXED)
    reports = query.order_by(DriverReport.created_at.desc(), DriverReport.id.desc()).all()
    return [_defect_read(r) for r in reports]


@router.post("/maintenance/defects/{report_id}/out-of-service", response_model=DefectReportRead)
def defect_out_of_service(
    report_id: int,
    payload: DefectOutOfService,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> DefectReportRead:
    """Takes the reported bus out of service from now (a repair window)."""
    report = _defect(db, report_id)
    if report.vehicle_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This report isn't linked to a bus; add a maintenance window for it instead",
        )
    if report.status != DefectStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This report has already been dealt with"
        )
    now = maintenance.district_now(db)
    until = _wall(payload.until) if payload.until is not None else None
    if until is not None and until <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="It must be back after now"
        )
    text = (
        report.description if len(report.description) <= 200 else report.description[:197] + "..."
    )
    window = MaintenanceWindow(
        vehicle_id=report.vehicle_id,
        kind=MaintenanceKind.REPAIR,
        starts_at=now,
        ends_at=until,
        reason=f"Defect: {text}",
        driver_report_id=report.id,
        created_by_user_id=current_user.id,
    )
    db.add(window)
    report.status = DefectStatus.OUT_OF_SERVICE
    db.flush()
    record_audit(
        db,
        entity_type="vehicle",
        entity_id=report.vehicle_id,
        action="out_of_service_for_defect",
        actor=current_user,
        after_state={"report_id": report.id, "window_id": window.id},
    )
    db.commit()
    db.refresh(report)
    return _defect_read(report)


@router.post("/maintenance/defects/{report_id}/fixed", response_model=DefectReportRead)
def defect_fixed(
    report_id: int,
    payload: DefectFixed,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> DefectReportRead:
    """The defect is fixed: the report closes, and the bus is back in
    service if it was taken out for it."""
    report = _defect(db, report_id)
    if report.status == DefectStatus.FIXED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already marked fixed")
    now = maintenance.district_now(db)
    for window in (
        db.query(MaintenanceWindow)
        .filter(
            MaintenanceWindow.driver_report_id == report.id,
            (MaintenanceWindow.ends_at.is_(None)) | (MaintenanceWindow.ends_at > now),
        )
        .all()
    ):
        _end_window(db, window, current_user)
    _mark_fixed(report, payload.note.strip(), current_user)
    record_audit(
        db,
        entity_type="driver_report",
        entity_id=report.id,
        action="defect_fixed",
        actor=current_user,
        after_state={"note": report.resolution_note},
    )
    db.commit()
    db.refresh(report)
    return _defect_read(report)


# --- Spare buses -------------------------------------------------------------


def _crew(db: Session, crew_id: int) -> Crew:
    crew = db.get(Crew, crew_id)
    if crew is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    return crew


@router.get("/assignments/{assignment_id}/spare-vehicles", response_model=SparesRead)
def list_spare_vehicles(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_ROLES)),
) -> SparesRead:
    """Buses that could take over the whole day of the crew doing this
    assignment (smallest fit first). The "needs a bus" alert points here."""
    assignment = db.get(Assignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found")
    crew = assignment.crew
    return SparesRead(
        crew_id=crew.id,
        current_vehicle_label=crew.vehicle.label,
        spares=[
            SpareVehicleRead(
                vehicle_id=s.vehicle.id,
                label=s.vehicle.label,
                allowable_capacity=s.vehicle.allowable_capacity(),
                spare_seats=s.spare_seats,
            )
            for s in maintenance.spare_vehicles(db, crew)
        ],
    )


@router.put("/crews/{crew_id}/vehicle", response_model=CrewRead)
def swap_crew_vehicle(
    crew_id: int,
    payload: CrewVehicleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_ROLES)),
) -> Crew:
    """Puts a spare bus on this crew; its driver keeps their runs."""
    crew = _crew(db, crew_id)
    if payload.vehicle_id == crew.vehicle_id:
        return crew
    if payload.vehicle_id not in {s.vehicle.id for s in maintenance.spare_vehicles(db, crew)}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That bus can't take over this crew's work (see the spare buses offered)",
        )
    before = crew.vehicle_id
    crew.vehicle_id = payload.vehicle_id
    db.flush()
    record_audit(
        db,
        entity_type="crew",
        entity_id=crew.id,
        action="vehicle_swapped",
        actor=current_user,
        before_state={"vehicle_id": before},
        after_state={"vehicle_id": crew.vehicle_id},
    )
    db.commit()
    db.refresh(crew)
    return crew
