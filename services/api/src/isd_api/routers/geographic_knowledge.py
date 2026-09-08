"""spec section 8: district-specific geographic knowledge overrides.
Authorized transportation personnel record local roadway knowledge
that commercial mapping data doesn't have. Per ADR 0007, this is the
one piece of routing-relevant data this system owns itself; spec
section 8's own text defers wiring it into route calculations to
future work, so this router only persists and lists it (POST/GET),
same scope as routers/stops.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import GeographicKnowledgeOverride, Role, User
from isd_api.schemas import GeographicKnowledgeOverrideCreate, GeographicKnowledgeOverrideRead
from isd_api.security import require_role

router = APIRouter(prefix="/geographic-knowledge", tags=["geographic-knowledge"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


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
    override = GeographicKnowledgeOverride(
        location_lat=payload.location_lat,
        location_lon=payload.location_lon,
        category=payload.category,
        note=payload.note,
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
