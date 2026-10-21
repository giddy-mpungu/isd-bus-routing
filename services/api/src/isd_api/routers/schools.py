from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from isd_api import zones
from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Role, School, User
from isd_api.schemas import SchoolCreate, SchoolRead, SchoolUpdate, SchoolZoneUpdate
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/schools", tags=["schools"])


@router.post("", response_model=SchoolRead, status_code=status.HTTP_201_CREATED)
def create_school(
    payload: SchoolCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> School:
    school = School(
        name=payload.name,
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
        external_id=payload.external_id,
    )
    db.add(school)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another school already has that SIS ID",
        ) from exc
    db.refresh(school)
    return school


@router.patch("/{school_id}", response_model=SchoolRead)
def update_school(
    school_id: int,
    payload: SchoolUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> School:
    """Name, location, and the SIS mapping (OneRoster org sourcedId) used by
    the roster import. Only the fields sent change; an explicit null for
    external_id clears the mapping."""
    school = db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    sent = payload.model_fields_set
    for field in ("name", "location_lat", "location_lon"):
        if field in sent and getattr(payload, field) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field} can't be empty"
            )

    fields = ("name", "location_lat", "location_lon", "external_id")
    before = {f: getattr(school, f) for f in fields}
    for field in fields:
        if field in sent:
            setattr(school, field, getattr(payload, field))
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another school already has that SIS ID",
        ) from exc
    after = {f: getattr(school, f) for f in fields}
    if after != before:
        record_audit(
            db,
            entity_type="school",
            entity_id=school.id,
            action="updated",
            actor=current_user,
            before_state=before,
            after_state=after,
        )
    db.commit()
    db.refresh(school)
    return school


@router.get("", response_model=list[SchoolRead])
def list_schools(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[School]:
    return list(db.query(School).order_by(School.id).all())


def _school_or_404(db: Session, school_id: int) -> School:
    school = db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    return school


@router.get("/{school_id}/zone")
def get_school_zone(
    school_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> dict | None:
    """Spec section 3: the school's attendance zone as GeoJSON, or null."""
    return _school_or_404(db, school_id).zone_geojson


@router.put("/{school_id}/zone", response_model=SchoolRead)
def set_school_zone(
    school_id: int,
    payload: SchoolZoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> School:
    """The school's boundary from the district's GIS (a GeoJSON Polygon or
    MultiPolygon, or a Feature/one-feature collection holding one). Homes
    outside it aren't eligible for the bus, except for specialized
    transportation (isd_api/eligibility.py)."""
    school = _school_or_404(db, school_id)
    try:
        geometry = zones.geometry_from_upload(payload.geojson)
    except zones.ZoneError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from None
    school.zone_geojson = geometry
    record_audit(
        db,
        entity_type="school",
        entity_id=school.id,
        action="zone_set",
        actor=current_user,
        after_state={"type": geometry["type"]},
    )
    db.commit()
    db.refresh(school)
    return school


@router.delete("/{school_id}/zone", response_model=SchoolRead)
def remove_school_zone(
    school_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> School:
    school = _school_or_404(db, school_id)
    school.zone_geojson = None
    record_audit(
        db, entity_type="school", entity_id=school.id, action="zone_removed", actor=current_user
    )
    db.commit()
    db.refresh(school)
    return school
