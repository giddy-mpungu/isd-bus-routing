"""spec section 17: Transportation Administrator's "Reports" /
"Historical records" access, and spec section 21's audit trail made
actually readable. Every mutation across this system already writes
to AuditLogEntry (isd_api.audit.record) -- this router is the first
place anything reads it back. transportation_admin only, not
dispatcher: before/after states can carry other users' operational
data across every entity in the system, a broader view than
dispatcher's own day-to-day scope elsewhere."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import AuditLogEntry, Role, User
from isd_api.schemas import AuditLogEntryRead
from isd_api.security import require_role

router = APIRouter(prefix="/audit-log", tags=["audit-log"])

_MAX_LIMIT = 500


@router.get("", response_model=list[AuditLogEntryRead])
def list_audit_log(
    entity_type: str | None = None,
    entity_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> list[AuditLogEntryRead]:
    query = db.query(AuditLogEntry)
    if entity_type is not None:
        query = query.filter(AuditLogEntry.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditLogEntry.entity_id == entity_id)
    if since is not None:
        query = query.filter(AuditLogEntry.created_at >= since)
    if until is not None:
        query = query.filter(AuditLogEntry.created_at <= until)
    entries = (
        query.order_by(AuditLogEntry.created_at.desc(), AuditLogEntry.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # One query for every distinct actor on this page, rather than a
    # join or a query per row -- AuditLogEntry deliberately has no ORM
    # relationship back to User (models.py's own docstring), so this
    # is the one place that resolves actor_user_id to a name for
    # display, kept local to this endpoint rather than adding that
    # relationship everywhere.
    actor_ids = {e.actor_user_id for e in entries if e.actor_user_id is not None}
    actors = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(actor_ids)).all()}

    return [
        AuditLogEntryRead(
            id=e.id,
            entity_type=e.entity_type,
            entity_id=e.entity_id,
            action=e.action,
            actor_user_id=e.actor_user_id,
            actor_full_name=actors.get(e.actor_user_id) if e.actor_user_id is not None else None,
            before_state=e.before_state,
            after_state=e.after_state,
            created_at=e.created_at,
        )
        for e in entries
    ]


@router.get("/entity-types", response_model=list[str])
def list_audit_log_entity_types(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> list[str]:
    """Populates the entity_type filter dropdown with values that
    actually occur, rather than a hardcoded list this router would
    need to keep in sync with every other router's record_audit calls."""
    rows = db.query(AuditLogEntry.entity_type).distinct().order_by(AuditLogEntry.entity_type).all()
    return [row[0] for row in rows]
