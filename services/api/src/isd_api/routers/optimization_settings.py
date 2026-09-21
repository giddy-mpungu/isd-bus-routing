"""Configurable soft-constraint objective weights (spec section 2.2;
spec section 17 lists "optimization parameters" under the Transportation
Administrator). Dispatchers may read them (the Schedule page explains the
result in their terms); only a transportation administrator changes them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from isd_solver import ObjectiveWeights
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import OptimizationSettings, Role, User
from isd_api.schemas import OptimizationSettingsRead, OptimizationSettingsUpdate
from isd_api.security import require_role

router = APIRouter(prefix="/optimization-settings", tags=["optimization-settings"])

_SETTINGS_ID = 1
_DEFAULTS = ObjectiveWeights()


def load_objective_weights(db: Session) -> ObjectiveWeights:
    """The weights the solver should use: the saved row, else defaults."""
    row = db.get(OptimizationSettings, _SETTINGS_ID)
    if row is None:
        return _DEFAULTS
    return ObjectiveWeights(
        crews_used=row.crews_used_weight,
        deadhead_minutes=row.deadhead_minutes_weight,
        arrival_buffer=row.arrival_buffer_weight,
    )


def _read(db: Session) -> OptimizationSettingsRead:
    weights = load_objective_weights(db)
    return OptimizationSettingsRead(
        crews_used_weight=weights.crews_used,
        deadhead_minutes_weight=weights.deadhead_minutes,
        arrival_buffer_weight=weights.arrival_buffer,
        is_default=db.get(OptimizationSettings, _SETTINGS_ID) is None,
    )


@router.get("", response_model=OptimizationSettingsRead)
def get_optimization_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> OptimizationSettingsRead:
    return _read(db)


@router.put("", response_model=OptimizationSettingsRead)
def update_optimization_settings(
    payload: OptimizationSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> OptimizationSettingsRead:
    before = _read(db)
    row = db.get(OptimizationSettings, _SETTINGS_ID)
    if row is None:
        row = OptimizationSettings(id=_SETTINGS_ID)
        db.add(row)
    row.crews_used_weight = payload.crews_used_weight
    row.deadhead_minutes_weight = payload.deadhead_minutes_weight
    row.arrival_buffer_weight = payload.arrival_buffer_weight
    db.flush()
    record_audit(
        db,
        entity_type="optimization_settings",
        entity_id=_SETTINGS_ID,
        action="updated",
        actor=current_user,
        before_state=before.model_dump(exclude={"is_default"}),
        after_state=payload.model_dump(),
    )
    db.commit()
    return _read(db)
