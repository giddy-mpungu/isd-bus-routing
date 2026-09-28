"""Operational alerts for dispatch: see isd_api/alerts.py."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from isd_api.alerts import day_alerts
from isd_api.db import get_db
from isd_api.models import Role, User
from isd_api.schemas import AlertRead, DayAlertsRead
from isd_api.security import require_role

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=DayAlertsRead)
def list_alerts(
    service_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> DayAlertsRead:
    """What needs attention on `service_date`, most urgent first. Read-only
    and derived each time, so it's always current."""
    result = day_alerts(db, service_date)
    return DayAlertsRead(
        service_date=service_date,
        district_time=result.district_time,
        alerts=[AlertRead(**asdict(a)) for a in result.alerts],
    )
