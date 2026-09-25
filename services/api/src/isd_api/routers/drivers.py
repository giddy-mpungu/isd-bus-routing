from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.licensing import license_class_from_codes
from isd_api.models import Driver, Role, User
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.schemas import DriverCreate, DriverRead, DriverUpdate
from isd_api.security import require_role

router = APIRouter(prefix="/drivers", tags=["drivers"])


@router.post("", response_model=DriverRead, status_code=status.HTTP_201_CREATED)
def create_driver(
    payload: DriverCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Driver:
    driver = Driver(
        full_name=payload.full_name,
        max_continuous_minutes=payload.max_continuous_minutes,
        qualifications=_resolve_qualifications(db, payload.qualification_codes),
        license_class=payload.license_class
        or license_class_from_codes(payload.qualification_codes),
    )
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@router.get("", response_model=list[DriverRead])
def list_drivers(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[Driver]:
    """Active and inactive alike -- see list_vehicles' identical note."""
    return list(db.query(Driver).order_by(Driver.id).all())


@router.patch("/{driver_id}", response_model=DriverRead)
def update_driver(
    driver_id: int,
    payload: DriverUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Driver:
    """Edits an existing driver's record, and/or marks them inactive
    (spec section 21 "reassign drivers"). Never a hard delete -- see
    update_vehicle's identical reasoning; a departed driver's historical
    Crew/Assignment/DriverAbsence/DriverReport rows must stay meaningful,
    and the User account linking to them (if any) is untouched here."""
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    before_state = {
        "full_name": driver.full_name,
        "max_continuous_minutes": driver.max_continuous_minutes,
        "is_active": driver.is_active,
        "qualification_codes": sorted(q.code for q in driver.qualifications),
        "license_class": driver.license_class.value if driver.license_class else None,
    }
    if "license_class" in payload.model_fields_set:
        driver.license_class = payload.license_class
    if payload.full_name is not None:
        driver.full_name = payload.full_name
    if payload.max_continuous_minutes is not None:
        driver.max_continuous_minutes = payload.max_continuous_minutes
    if payload.is_active is not None:
        driver.is_active = payload.is_active
    if payload.qualification_codes is not None:
        driver.qualifications = _resolve_qualifications(db, payload.qualification_codes)

    db.flush()
    record_audit(
        db,
        entity_type="driver",
        entity_id=driver.id,
        action="updated",
        actor=current_user,
        before_state=before_state,
        after_state={
            "full_name": driver.full_name,
            "max_continuous_minutes": driver.max_continuous_minutes,
            "is_active": driver.is_active,
            "qualification_codes": sorted(q.code for q in driver.qualifications),
            "license_class": driver.license_class.value if driver.license_class else None,
        },
    )
    db.commit()
    db.refresh(driver)
    return driver
