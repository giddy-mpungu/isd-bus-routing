"""spec section 8: district-specific geographic knowledge overrides.
Authorized transportation personnel record local roadway knowledge
that commercial mapping data doesn't have. Per ADR 0007, this is the
one piece of routing-relevant data this system owns itself. This
router persists and lists it (POST/GET); routers/schedule.py is where
CONGESTION_WINDOW and VEHICLE_SIZE_RESTRICTED overrides actually get
applied to a solve (FREQUENT_FLOODING/UNSAFE_TURN/INVALID_TURNAROUND
already did, from an earlier slice) -- see that module's
_HARD_AVOID_CATEGORIES and _size_restrictions_for_schedule."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import GeographicKnowledgeCategory, GeographicKnowledgeOverride, Role, User
from isd_api.schemas import GeographicKnowledgeOverrideCreate, GeographicKnowledgeOverrideRead
from isd_api.security import require_role

router = APIRouter(prefix="/geographic-knowledge", tags=["geographic-knowledge"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


def _validate_category_specific_fields(payload: GeographicKnowledgeOverrideCreate) -> None:
    """CONGESTION_WINDOW and VEHICLE_SIZE_RESTRICTED each need their own
    routing-relevant fields, required together and only meaningful for
    that one category — every other category must leave all four
    null, so a stale window/threshold from a since-changed category
    can never linger and silently get applied to routing."""
    is_congestion = payload.category == GeographicKnowledgeCategory.CONGESTION_WINDOW
    is_size_restricted = payload.category == GeographicKnowledgeCategory.VEHICLE_SIZE_RESTRICTED

    if is_congestion:
        if payload.window_start_minute is None or payload.window_end_minute is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="congestion_window requires both window_start_minute and window_end_minute",
            )
        if payload.window_start_minute > payload.window_end_minute:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="window_start_minute must be <= window_end_minute",
            )
    elif payload.window_start_minute is not None or payload.window_end_minute is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="window_start_minute/window_end_minute are only valid for congestion_window",
        )

    if is_size_restricted:
        if payload.restricted_dimension is None or payload.max_allowed_value is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "vehicle_size_restricted requires both restricted_dimension and "
                    "max_allowed_value"
                ),
            )
    elif payload.restricted_dimension is not None or payload.max_allowed_value is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "restricted_dimension/max_allowed_value are only valid for vehicle_size_restricted"
            ),
        )


@router.post(
    "", response_model=GeographicKnowledgeOverrideRead, status_code=status.HTTP_201_CREATED
)
def create_geographic_knowledge_override(
    payload: GeographicKnowledgeOverrideCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> GeographicKnowledgeOverride:
    """Both transportation_admin and dispatcher can add these — day-to-day
    operational knowledge (e.g. a dispatcher entering a flooded street
    after a driver's phone call), not structural master data, so this
    follows the broader RBAC precedent set by absences.py rather than
    stops.py's admin-only one."""
    _validate_category_specific_fields(payload)
    override = GeographicKnowledgeOverride(
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
        category=payload.category,
        note=payload.note,
        window_start_minute=payload.window_start_minute,
        window_end_minute=payload.window_end_minute,
        restricted_dimension=payload.restricted_dimension,
        max_allowed_value=payload.max_allowed_value,
    )
    db.add(override)
    db.flush()
    record_audit(
        db,
        entity_type="geographic_knowledge_override",
        entity_id=override.id,
        action="created",
        actor=current_user,
        after_state={
            "location_lat": payload.location_lat,
            "location_lon": payload.location_lon,
            "category": payload.category.value,
            "note": payload.note,
            "window_start_minute": payload.window_start_minute,
            "window_end_minute": payload.window_end_minute,
            "restricted_dimension": (
                payload.restricted_dimension.value if payload.restricted_dimension else None
            ),
            "max_allowed_value": payload.max_allowed_value,
        },
    )
    db.commit()
    db.refresh(override)
    return override


@router.get("", response_model=list[GeographicKnowledgeOverrideRead])
def list_geographic_knowledge_overrides(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[GeographicKnowledgeOverride]:
    return list(
        db.query(GeographicKnowledgeOverride).order_by(GeographicKnowledgeOverride.id).all()
    )
