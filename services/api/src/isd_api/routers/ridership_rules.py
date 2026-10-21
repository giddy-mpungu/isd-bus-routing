"""District ridership reporting rules (spec section 4.4). Transportation
administrators set them; dispatchers can read them. Families see their
effect in GET /students/my-family (am_changes_closed / pm_changes_closed)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import RidershipRules, Role, User
from isd_api.ridership_rules import load_rules
from isd_api.schemas import RidershipRulesRead, RidershipRulesUpdate
from isd_api.security import require_role

router = APIRouter(prefix="/ridership-rules", tags=["ridership-rules"])

_RULES_ID = 1


def _read(db: Session) -> RidershipRulesRead:
    rules = load_rules(db)
    return RidershipRulesRead(
        timezone=rules.timezone,
        am_cutoff_minute=rules.am_cutoff_minute,
        pm_cutoff_minute=rules.pm_cutoff_minute,
        route_lock_minutes=rules.route_lock_minutes,
        is_default=rules.is_default,
    )


@router.get("", response_model=RidershipRulesRead)
def get_ridership_rules(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> RidershipRulesRead:
    return _read(db)


@router.put("", response_model=RidershipRulesRead)
def update_ridership_rules(
    payload: RidershipRulesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> RidershipRulesRead:
    before = _read(db)
    row = db.get(RidershipRules, _RULES_ID)
    if row is None:
        row = RidershipRules(id=_RULES_ID)
        db.add(row)
    row.timezone = payload.timezone
    row.am_cutoff_minute = payload.am_cutoff_minute
    row.pm_cutoff_minute = payload.pm_cutoff_minute
    row.route_lock_minutes = payload.route_lock_minutes
    db.flush()
    record_audit(
        db,
        entity_type="ridership_rules",
        entity_id=_RULES_ID,
        action="updated",
        actor=current_user,
        before_state=before.model_dump(exclude={"is_default"}),
        after_state=payload.model_dump(),
    )
    db.commit()
    return _read(db)
