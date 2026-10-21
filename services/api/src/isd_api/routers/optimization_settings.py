"""Configurable soft-constraint objective weights (spec section 2.2;
spec section 17 lists "optimization parameters" under the Transportation
Administrator). Dispatchers may read them (the Schedule page explains the
result in their terms); only a transportation administrator changes them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from isd_solver import ObjectiveWeights, WorkRules
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


def load_minimum_buffer_minutes(db: Session) -> int:
    """Spec section 16's minimum buffer between consecutive runs (0 = none)."""
    row = db.get(OptimizationSettings, _SETTINGS_ID)
    return 0 if row is None else row.minimum_buffer_minutes


def load_work_rules(db: Session) -> WorkRules:
    """The district's driver work-hour rules for the solver (all off by default)."""
    row = db.get(OptimizationSettings, _SETTINGS_ID)
    if row is None:
        return WorkRules()
    return WorkRules(
        max_duty_minutes=row.max_duty_minutes,
        break_after_minutes=row.break_after_minutes,
        break_minutes=row.break_minutes,
    )


def load_ride_time_weight(db: Session) -> int:
    """Route planning's weight on students' ride time (0 = fastest route)."""
    row = db.get(OptimizationSettings, _SETTINGS_ID)
    return 0 if row is None else row.ride_time_weight


def load_walking_weight(db: Session) -> int:
    """Proposing stops: 0 walks up to each grade's limit; each step takes
    5% off it, for shorter walks at the cost of more stops."""
    row = db.get(OptimizationSettings, _SETTINGS_ID)
    return 0 if row is None else row.walking_weight


def load_min_rest_minutes(db: Session) -> int | None:
    """Minutes off required between a driver's days (None = no rule)."""
    row = db.get(OptimizationSettings, _SETTINGS_ID)
    return None if row is None else row.min_rest_minutes


def _read(db: Session) -> OptimizationSettingsRead:
    weights = load_objective_weights(db)
    rules = load_work_rules(db)
    return OptimizationSettingsRead(
        crews_used_weight=weights.crews_used,
        deadhead_minutes_weight=weights.deadhead_minutes,
        arrival_buffer_weight=weights.arrival_buffer,
        minimum_buffer_minutes=load_minimum_buffer_minutes(db),
        ride_time_weight=load_ride_time_weight(db),
        walking_weight=load_walking_weight(db),
        max_duty_minutes=rules.max_duty_minutes,
        break_after_minutes=rules.break_after_minutes,
        break_minutes=rules.break_minutes,
        min_rest_minutes=load_min_rest_minutes(db),
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
    row.minimum_buffer_minutes = payload.minimum_buffer_minutes
    row.ride_time_weight = payload.ride_time_weight
    row.walking_weight = payload.walking_weight
    row.max_duty_minutes = payload.max_duty_minutes
    row.break_after_minutes = payload.break_after_minutes
    row.break_minutes = payload.break_minutes
    row.min_rest_minutes = payload.min_rest_minutes
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
