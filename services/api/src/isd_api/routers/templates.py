"""Recurring templates (spec section 11 "Permanent Assignment", ADR 0001's
never-built Route): RouteTemplate generates Runs, CrewTemplate generates
Crews. Generation is an explicit, idempotent, create-only action -- it
never edits or deletes an existing Run/Crew, so every day-level
exception (locks, substitutions, absences) keeps working untouched, and
it never runs the solver (spec section 21: a dispatcher reviews the
generated day, then solves).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.availability import resource_unavailable_reason
from isd_api.db import get_db
from isd_api.models import (
    Crew,
    CrewTemplate,
    Driver,
    DriverAbsence,
    Role,
    RouteTemplate,
    Run,
    School,
    User,
    Vehicle,
)
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.schemas import (
    CrewTemplateCreate,
    CrewTemplateRead,
    GenerateFromTemplatesRead,
    RouteTemplateCreate,
    RouteTemplateRead,
    TemplateUpdate,
)
from isd_api.security import require_role

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)

route_router = APIRouter(prefix="/route-templates", tags=["templates"])
crew_router = APIRouter(prefix="/crew-templates", tags=["templates"])
generate_router = APIRouter(prefix="/schedule", tags=["templates"])


def _check_active_range(active_from: date | None, active_until: date | None) -> None:
    if active_from is not None and active_until is not None and active_from > active_until:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="active_from must be <= active_until",
        )


def _applies_on(template: RouteTemplate | CrewTemplate, service_date: date) -> bool:
    return (
        template.is_active
        and service_date.weekday() in template.days_of_week
        and (template.active_from is None or template.active_from <= service_date)
        and (template.active_until is None or template.active_until >= service_date)
    )


@route_router.post("", response_model=RouteTemplateRead, status_code=status.HTTP_201_CREATED)
def create_route_template(
    payload: RouteTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> RouteTemplate:
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
            detail="duration_minutes + buffer_minutes exceeds the route's own window length",
        )
    _check_active_range(payload.active_from, payload.active_until)
    if db.get(School, payload.school_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")

    template = RouteTemplate(
        school_id=payload.school_id,
        direction=payload.direction,
        window_earliest=payload.window_earliest,
        window_latest=payload.window_latest,
        duration_minutes=payload.duration_minutes,
        buffer_minutes=payload.buffer_minutes,
        days_of_week=payload.days_of_week,
        active_from=payload.active_from,
        active_until=payload.active_until,
        required_qualifications=_resolve_qualifications(db, payload.required_qualification_codes),
    )
    db.add(template)
    db.flush()
    record_audit(
        db,
        entity_type="route_template",
        entity_id=template.id,
        action="created",
        actor=current_user,
        after_state={
            "school_id": template.school_id,
            "direction": template.direction.value,
            "days_of_week": template.days_of_week,
        },
    )
    db.commit()
    db.refresh(template)
    return template


@route_router.get("", response_model=list[RouteTemplateRead])
def list_route_templates(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[RouteTemplate]:
    return list(db.query(RouteTemplate).order_by(RouteTemplate.id).all())


@route_router.patch("/{template_id}", response_model=RouteTemplateRead)
def update_route_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> RouteTemplate:
    template = db.get(RouteTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route template not found"
        )
    before = {"is_active": template.is_active}
    template.is_active = payload.is_active
    db.flush()
    record_audit(
        db,
        entity_type="route_template",
        entity_id=template.id,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state={"is_active": template.is_active},
    )
    db.commit()
    db.refresh(template)
    return template


@crew_router.post("", response_model=CrewTemplateRead, status_code=status.HTTP_201_CREATED)
def create_crew_template(
    payload: CrewTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> CrewTemplate:
    if payload.available_window_earliest > payload.available_window_latest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="available_window_earliest must be <= available_window_latest",
        )
    _check_active_range(payload.active_from, payload.active_until)
    if db.get(Driver, payload.driver_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    if db.get(Vehicle, payload.vehicle_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown vehicle_id")

    template = CrewTemplate(
        driver_id=payload.driver_id,
        vehicle_id=payload.vehicle_id,
        available_window_earliest=payload.available_window_earliest,
        available_window_latest=payload.available_window_latest,
        days_of_week=payload.days_of_week,
        active_from=payload.active_from,
        active_until=payload.active_until,
    )
    db.add(template)
    db.flush()
    record_audit(
        db,
        entity_type="crew_template",
        entity_id=template.id,
        action="created",
        actor=current_user,
        after_state={
            "driver_id": template.driver_id,
            "vehicle_id": template.vehicle_id,
            "days_of_week": template.days_of_week,
        },
    )
    db.commit()
    db.refresh(template)
    return template


@crew_router.get("", response_model=list[CrewTemplateRead])
def list_crew_templates(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[CrewTemplate]:
    return list(db.query(CrewTemplate).order_by(CrewTemplate.id).all())


@crew_router.patch("/{template_id}", response_model=CrewTemplateRead)
def update_crew_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> CrewTemplate:
    template = db.get(CrewTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew template not found")
    before = {"is_active": template.is_active}
    template.is_active = payload.is_active
    db.flush()
    record_audit(
        db,
        entity_type="crew_template",
        entity_id=template.id,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state={"is_active": template.is_active},
    )
    db.commit()
    db.refresh(template)
    return template


@generate_router.post(
    "/{service_date}/generate-from-templates", response_model=GenerateFromTemplatesRead
)
def generate_from_templates(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> GenerateFromTemplatesRead:
    """Creates that day's Runs and Crews from every active template that
    applies to its weekday and date range. Idempotent: a template that
    already produced a Run/Crew for the date is skipped, and a crew
    template is also skipped when its driver or vehicle already has any
    crew that day (hand-made or generated) -- the per-day uniqueness
    constraints would reject it anyway, and an existing row always wins.
    A crew whose driver has an absence fully covering the template's
    window is skipped; partial-day absences still generate, and the
    absences workflow handles substitutes.
    """
    runs_created = runs_existing = crews_created = crews_existing = 0
    absent_driver_ids: list[int] = []
    out_of_service_template_ids: list[int] = []

    for rt in db.query(RouteTemplate).order_by(RouteTemplate.id).all():
        if not _applies_on(rt, service_date):
            continue
        already = (
            db.query(Run)
            .filter(Run.route_template_id == rt.id, Run.service_date == service_date)
            .first()
        )
        if already is not None:
            runs_existing += 1
            continue
        run = Run(
            service_date=service_date,
            school_id=rt.school_id,
            direction=rt.direction,
            window_earliest=rt.window_earliest,
            window_latest=rt.window_latest,
            duration_minutes=rt.duration_minutes,
            buffer_minutes=rt.buffer_minutes,
            passenger_count=0,
            route_template_id=rt.id,
            required_qualifications=list(rt.required_qualifications),
        )
        db.add(run)
        db.flush()
        record_audit(
            db,
            entity_type="run",
            entity_id=run.id,
            action="generated_from_template",
            actor=current_user,
            after_state={"route_template_id": rt.id, "service_date": service_date.isoformat()},
        )
        runs_created += 1

    for ct in db.query(CrewTemplate).order_by(CrewTemplate.id).all():
        if not _applies_on(ct, service_date):
            continue
        clash = (
            db.query(Crew)
            .filter(
                Crew.service_date == service_date,
                (Crew.crew_template_id == ct.id)
                | (Crew.driver_id == ct.driver_id)
                | (Crew.vehicle_id == ct.vehicle_id),
            )
            .first()
        )
        if clash is not None:
            crews_existing += 1
            continue
        if resource_unavailable_reason(ct.driver, ct.vehicle) is not None:
            out_of_service_template_ids.append(ct.id)
            continue
        fully_absent = (
            db.query(DriverAbsence)
            .filter(
                DriverAbsence.driver_id == ct.driver_id,
                DriverAbsence.service_date == service_date,
                DriverAbsence.start_minute <= ct.available_window_earliest,
                DriverAbsence.end_minute >= ct.available_window_latest,
            )
            .first()
            is not None
        )
        if fully_absent:
            absent_driver_ids.append(ct.driver_id)
            continue
        crew = Crew(
            service_date=service_date,
            driver_id=ct.driver_id,
            vehicle_id=ct.vehicle_id,
            available_window_earliest=ct.available_window_earliest,
            available_window_latest=ct.available_window_latest,
            crew_template_id=ct.id,
        )
        db.add(crew)
        db.flush()
        record_audit(
            db,
            entity_type="crew",
            entity_id=crew.id,
            action="generated_from_template",
            actor=current_user,
            after_state={"crew_template_id": ct.id, "service_date": service_date.isoformat()},
        )
        crews_created += 1

    db.commit()
    return GenerateFromTemplatesRead(
        service_date=service_date,
        runs_created=runs_created,
        runs_already_existing=runs_existing,
        crews_created=crews_created,
        crews_already_existing=crews_existing,
        crews_skipped_absent_driver_ids=absent_driver_ids,
        crews_skipped_out_of_service_template_ids=out_of_service_template_ids,
    )
