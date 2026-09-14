"""spec sections 9/18: dispatcher-authored notices for drivers and/or
families. See models.Announcement's docstring for why these are
always human-authored (no ETA engine, no automatic event-to-
notification pipeline exists in this system) and district-wide only
in this first slice (no per-school scoping)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Announcement, AnnouncementAudience, Role, User
from isd_api.schemas import AnnouncementCreate, AnnouncementRead
from isd_api.security import require_role

router = APIRouter(prefix="/announcements", tags=["announcements"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)
_RECIPIENT_ROLES = (Role.DRIVER, Role.STUDENT, Role.PARENT)


@router.post("", response_model=AnnouncementRead, status_code=status.HTTP_201_CREATED)
def create_announcement(
    payload: AnnouncementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> Announcement:
    announcement = Announcement(
        message=payload.message,
        category=payload.category,
        audience=payload.audience,
    )
    db.add(announcement)
    db.flush()
    record_audit(
        db,
        entity_type="announcement",
        entity_id=announcement.id,
        action="created",
        actor=current_user,
        after_state={
            "message": announcement.message,
            "category": announcement.category.value,
            "audience": announcement.audience.value,
        },
    )
    db.commit()
    db.refresh(announcement)
    return announcement


@router.get("", response_model=list[AnnouncementRead])
def list_announcements(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[Announcement]:
    """Full list, for dispatcher/admin oversight -- recipients use
    GET /announcements/mine instead, which is filtered to their own
    audience."""
    return list(db.query(Announcement).order_by(Announcement.created_at.desc()).all())


@router.get("/mine", response_model=list[AnnouncementRead])
def list_my_announcements(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_RECIPIENT_ROLES)),
) -> list[Announcement]:
    audience = (
        AnnouncementAudience.DRIVER
        if current_user.role == Role.DRIVER
        else AnnouncementAudience.FAMILY
    )
    return list(
        db.query(Announcement)
        .filter(Announcement.audience.in_([AnnouncementAudience.ALL, audience]))
        .order_by(Announcement.created_at.desc())
        .all()
    )
