from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import Role, Run, School, User
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.schemas import RunCreate, RunRead
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunRead, status_code=status.HTTP_201_CREATED)
def create_run(
    payload: RunCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> Run:
    if payload.window_earliest > payload.window_latest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="window_earliest must be <= window_latest",
        )
    if payload.duration_minutes + payload.buffer_minutes > (
        payload.window_latest - payload.window_earliest
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duration_minutes + buffer_minutes exceeds the run's own window length",
        )
    if db.get(School, payload.school_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")

    run = Run(
        service_date=payload.service_date,
        school_id=payload.school_id,
        window_earliest=payload.window_earliest,
        window_latest=payload.window_latest,
        duration_minutes=payload.duration_minutes,
        buffer_minutes=payload.buffer_minutes,
        passenger_count=payload.passenger_count,
        required_qualifications=_resolve_qualifications(db, payload.required_qualification_codes),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.get("", response_model=list[RunRead])
def list_runs(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Run]:
    """spec section 17: School Administrator sees buses/runs serving
    their school; Dispatcher/Transportation Administrator see everything.
    Driver/Student/Parent have no direct run-listing access here — a
    driver's own upcoming work comes from /schedule/{date}/assignments,
    scoped to their crew.
    """
    query = db.query(Run).filter(Run.service_date == service_date)
    if current_user.role == Role.SCHOOL_ADMIN:
        if current_user.school_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This school_admin account is not linked to a school",
            )
        query = query.filter(Run.school_id == current_user.school_id)
    elif current_user.role not in (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role.value}' cannot list runs directly",
        )
    return list(query.order_by(Run.id).all())
