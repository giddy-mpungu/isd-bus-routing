"""spec section 12.3: reusable transportation-specific information for
a frequently used field-trip destination. Persistence only -- a
`FieldTrip` optionally links to one via `destination_profile_id`
(routers/field_trips.py); nothing here auto-matches a trip's free-text
`destination` to a profile, the dispatcher picks one explicitly."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import DestinationProfile, Role, User
from isd_api.schemas import DestinationProfileCreate, DestinationProfileRead
from isd_api.security import require_role

router = APIRouter(prefix="/destination-profiles", tags=["destination-profiles"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


@router.post("", response_model=DestinationProfileRead, status_code=status.HTTP_201_CREATED)
def create_destination_profile(
    payload: DestinationProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> DestinationProfile:
    profile = DestinationProfile(
        name=payload.name,
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
        approved_entrance=payload.approved_entrance,
        parking_notes=payload.parking_notes,
        turn_restrictions=payload.turn_restrictions,
        driver_notes=payload.driver_notes,
    )
    db.add(profile)
    db.flush()
    record_audit(
        db,
        entity_type="destination_profile",
        entity_id=profile.id,
        action="created",
        actor=current_user,
        after_state={"name": profile.name},
    )
    db.commit()
    db.refresh(profile)
    return profile


@router.get("", response_model=list[DestinationProfileRead])
def list_destination_profiles(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[DestinationProfile]:
    return list(db.query(DestinationProfile).order_by(DestinationProfile.name).all())
