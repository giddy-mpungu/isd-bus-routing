"""A parent's email choices (Phase 5.5): the Family page switch and the
"stop these emails" link in every bus-time email (isd_api/eta_notifications.py).

The link opens a web page with a button rather than turning emails off on
a plain GET, because mail security scanners open links in emails."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from isd_api import eta_notifications
from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import Role, User
from isd_api.schemas import EtaOptOut, NotificationSettings
from isd_api.security import password_rate_limiter, require_role

router = APIRouter(tags=["notifications"])


@router.get("/users/me/notification-settings", response_model=NotificationSettings)
def get_settings(current_user: User = Depends(require_role(Role.PARENT))) -> NotificationSettings:
    return NotificationSettings(eta_emails=current_user.eta_emails_enabled)


@router.put("/users/me/notification-settings", response_model=NotificationSettings)
def put_settings(
    payload: NotificationSettings,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.PARENT)),
) -> NotificationSettings:
    if payload.eta_emails != current_user.eta_emails_enabled:
        current_user.eta_emails_enabled = payload.eta_emails
        record_audit(
            db,
            entity_type="user",
            entity_id=current_user.id,
            action="eta_emails_on" if payload.eta_emails else "eta_emails_off",
            actor=current_user,
        )
        db.commit()
    return NotificationSettings(eta_emails=current_user.eta_emails_enabled)


@router.post("/notifications/eta/opt-out", status_code=status.HTTP_204_NO_CONTENT)
def opt_out(payload: EtaOptOut, request: Request, db: Session = Depends(get_db)) -> None:
    """From the link in an email; no sign-in needed."""
    password_rate_limiter.check(f"optout:{request.client.host if request.client else 'unknown'}")
    user = eta_notifications.user_for_opt_out(db, payload.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This link has expired. Turn bus time emails off on the Family page instead.",
        )
    if user.eta_emails_enabled:
        user.eta_emails_enabled = False
        record_audit(db, entity_type="user", entity_id=user.id, action="eta_emails_off", actor=user)
        db.commit()
