"""District transportation rules (spec section 3.1): the eligibility
distance, and walk and ride limits by grade band. Transportation
administrators set them; dispatchers can read them. See
isd_api/eligibility.py for what they mean and the defaults."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.eligibility import BAND_LABELS, BANDS, load_rules
from isd_api.models import Role, TransportationRules, User
from isd_api.schemas import TransportationRulesRead, TransportationRulesUpdate
from isd_api.security import require_role

router = APIRouter(prefix="/transportation-rules", tags=["transportation-rules"])

_RULES_ID = 1


def _read(db: Session) -> TransportationRulesRead:
    rules = load_rules(db)
    return TransportationRulesRead(
        eligibility_miles=rules.eligibility_miles,
        walk_miles=rules.walk_miles,
        ride_minutes=rules.ride_minutes,
        min_stop_spacing_miles=rules.min_stop_spacing_miles,
        band_labels=BAND_LABELS,
        is_default=rules.is_default,
    )


@router.get("", response_model=TransportationRulesRead)
def get_transportation_rules(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> TransportationRulesRead:
    return _read(db)


@router.put("", response_model=TransportationRulesRead)
def update_transportation_rules(
    payload: TransportationRulesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> TransportationRulesRead:
    before = _read(db)
    row = db.get(TransportationRules, _RULES_ID)
    if row is None:
        row = TransportationRules(
            id=_RULES_ID, min_stop_spacing_miles=before.min_stop_spacing_miles
        )
        db.add(row)
    row.eligibility_miles = payload.eligibility_miles
    if payload.min_stop_spacing_miles is not None:
        row.min_stop_spacing_miles = payload.min_stop_spacing_miles
    for band in BANDS:
        setattr(row, f"walk_miles_{band}", payload.walk_miles[band])
        setattr(row, f"ride_minutes_{band}", payload.ride_minutes[band])
    db.flush()
    record_audit(
        db,
        entity_type="transportation_rules",
        entity_id=_RULES_ID,
        action="updated",
        actor=current_user,
        before_state=before.model_dump(exclude={"is_default", "band_labels"}),
        after_state=payload.model_dump() | {"min_stop_spacing_miles": row.min_stop_spacing_miles},
    )
    db.commit()
    return _read(db)
