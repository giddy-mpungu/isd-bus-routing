"""Helper for writing to the append-only audit trail (spec section 14).

Routers call `record` after a successful DB write, never before —
audit entries should reflect what actually happened, not what was
attempted. `before_state`/`after_state` are plain dicts (JSON-
serializable) built by the caller from the entity, not the ORM object
itself, so this module has no coupling to specific model shapes.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from isd_api.models import AuditLogEntry, User


def record(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: User | None,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> AuditLogEntry:
    entry = AuditLogEntry(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor.id if actor else None,
        before_state=before_state,
        after_state=after_state,
    )
    db.add(entry)
    db.flush()
    return entry
