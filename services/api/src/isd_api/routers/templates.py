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
from isd_solver import Location, StopDemand, plan_route
from sqlalchemy.orm import Session

from isd_api import bells, eligibility
from isd_api.audit import record as record_audit
from isd_api.availability import resource_unavailable_reason, vehicle_blocks
from isd_api.db import get_db
from isd_api.licensing import license_violation
from isd_api.models import (
    Crew,
    CrewTemplate,
    Driver,
    DriverAbsence,
    Role,
    RouteStop,
    RouteTemplate,
    Run,
    School,
    Stop,
    Student,
    User,
    Vehicle,
)
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.schemas import (
    CrewTemplateCreate,
    CrewTemplateRead,
    GenerateFromTemplatesRead,
    PlannedRouteStop,
    RoutePlanRead,
    RoutePlanRequest,
    RouteStopRead,
    RouteStopsUpdate,
    RouteTemplateCreate,
    RouteTemplateRead,
    RouteTemplateUpdate,
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
    school = db.get(School, payload.school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")
    if payload.follows_bells:
        regular = bells.regular_schedule(school)
        if regular is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This school has no regular bell schedule to follow yet",
            )
        earliest, latest = bells.window(
            regular,
            bells.offsets_for(db, school),
            payload.direction,
            payload.duration_minutes,
            payload.buffer_minutes,
        )
    elif payload.window_earliest is None or payload.window_latest is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Give the route's window, or have it follow the school's bells",
        )
    else:
        earliest, latest = payload.window_earliest, payload.window_latest
    if earliest > latest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="window_earliest must be <= window_latest",
        )
    if payload.duration_minutes + payload.buffer_minutes > latest - earliest:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="duration_minutes + buffer_minutes exceeds the route's own window length",
        )
    _check_active_range(payload.active_from, payload.active_until)

    template = RouteTemplate(
        school_id=payload.school_id,
        direction=payload.direction,
        window_earliest=earliest,
        window_latest=latest,
        follows_bells=payload.follows_bells,
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
    payload: RouteTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> RouteTemplate:
    template = db.get(RouteTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route template not found"
        )
    before = {"is_active": template.is_active, "follows_bells": template.follows_bells}
    if payload.is_active is not None:
        template.is_active = payload.is_active
    if payload.follows_bells is not None and payload.follows_bells != template.follows_bells:
        if payload.follows_bells and bells.regular_schedule(template.school) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This school has no regular bell schedule to follow yet",
            )
        # Its own window stays as it is (the regular day's, while it
        # followed the bells) for days it no longer follows them.
        template.follows_bells = payload.follows_bells
    db.flush()
    moved = bells.refresh_windows(db, {template.school_id}) if template.follows_bells else []
    record_audit(
        db,
        entity_type="route_template",
        entity_id=template.id,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state={"is_active": template.is_active, "follows_bells": template.follows_bells},
    )
    bells.audit_moved_runs(db, moved, current_user)
    db.commit()
    db.refresh(template)
    return template


@route_router.get("/{template_id}/stops", response_model=list[RouteStopRead])
def get_route_stops(
    template_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[RouteStop]:
    return list(_route_or_404(db, template_id).stops)


@route_router.put("/{template_id}/stops", response_model=list[RouteStopRead])
def set_route_stops(
    template_id: int,
    payload: RouteStopsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> list[RouteStop]:
    """Spec sections 3 and 9: the route's stops, in the order the bus
    visits them. Replaces the whole list. Planned minutes from start, where
    given, must not go backwards and must fit in the route's duration."""
    template = _route_or_404(db, template_id)
    ids = [s.stop_id for s in payload.stops]
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A stop can appear on a route only once"
        )
    found = {s.id for s in db.query(Stop).filter(Stop.id.in_(ids))} if ids else set()
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown stop id(s): {missing}"
        )
    times = [s.minutes_from_start for s in payload.stops if s.minutes_from_start is not None]
    if any(later < earlier for earlier, later in zip(times, times[1:], strict=False)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Planned minutes from start can't go backwards along the route",
        )
    if times and times[-1] > template.duration_minutes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A stop is planned after the route's {template.duration_minutes}-minute duration"
            ),
        )

    before = [
        {"stop_id": s.stop_id, "minutes_from_start": s.minutes_from_start} for s in template.stops
    ]
    template.stops.clear()
    db.flush()
    for position, item in enumerate(payload.stops, start=1):
        template.stops.append(
            RouteStop(
                position=position,
                stop_id=item.stop_id,
                minutes_from_start=item.minutes_from_start,
            )
        )
    db.flush()
    record_audit(
        db,
        entity_type="route_template",
        entity_id=template.id,
        action="stops_updated",
        actor=current_user,
        before_state={"stops": before},
        after_state={"stops": [s.model_dump() for s in payload.stops]},
    )
    db.commit()
    db.refresh(template)
    return list(template.stops)


TRAVEL_ESTIMATE = (
    "Straight-line distance x 1.3 for roads, at 30 km/h, plus loading time at each stop. "
    "An estimate for ordering stops, not road-network travel times."
)


@route_router.post("/{template_id}/stops/plan", response_model=RoutePlanRead)
def plan_route_stops(
    template_id: int,
    payload: RoutePlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> RoutePlanRead:
    """Spec sections 2, 3.1 and 16: puts the route's stops in the order that
    takes least time, within the ride limit of the students at each stop,
    and plans the minutes from start. Morning routes end at school,
    afternoon routes start there. With `apply`, saves the order and times
    and sets the route's duration to the plan's total (runs already
    generated keep theirs)."""
    template = _route_or_404(db, template_id)
    if not template.stops:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Add stops to the route first"
        )
    rules = eligibility.load_rules(db)
    fallback_ride = min(
        v for band, v in rules.ride_minutes.items() if band != eligibility.SPECIALIZED
    )
    stop_ids = [rs.stop_id for rs in template.stops]
    students = (
        db.query(Student)
        .filter(
            Student.school_id == template.school_id,
            Student.stop_id.in_(stop_ids),
            Student.withdrawn_on.is_(None),  # left the district (FERPA retention)
        )
        .all()
    )
    by_stop: dict[int, list[Student]] = {}
    for student in students:
        by_stop.setdefault(student.stop_id or 0, []).append(student)

    def ride_limit(student: Student) -> int:
        band = eligibility.band_for(student)
        return fallback_ride if band is None else rules.ride_minutes[band]

    demands = []
    for rs in template.stops:
        riders = by_stop.get(rs.stop_id, [])
        demands.append(
            StopDemand(
                stop_id=rs.stop_id,
                location=Location(rs.stop.location_lat, rs.stop.location_lon),
                riders=len(riders),
                accommodation_riders=sum(1 for s in riders if s.accommodations),
                max_ride_minutes=min((ride_limit(s) for s in riders), default=None),
            )
        )
    plan = plan_route(
        Location(template.school.location_lat, template.school.location_lon),
        demands,
        direction=template.direction.value,
    )

    labels = {rs.stop_id: rs.stop.label for rs in template.stops}
    riders_at = {d.stop_id: d.riders for d in demands}
    planned = [
        PlannedRouteStop(
            position=position,
            stop_id=p.stop_id,
            stop_label=labels[p.stop_id],
            minutes_from_start=p.minutes_from_start,
            riders=riders_at[p.stop_id],
            ride_minutes=p.ride_minutes,
            ride_limit_minutes=p.max_ride_minutes,
        )
        for position, p in enumerate(plan.stops, start=1)
    ]
    violations = [
        f"{s.stop_label}: {s.ride_minutes}-minute ride (limit {s.ride_limit_minutes} min)"
        for s in planned
        if s.ride_limit_minutes is not None and s.ride_minutes > s.ride_limit_minutes
    ]
    current_duration = template.duration_minutes
    window = template.window_latest - template.window_earliest
    fits = plan.total_minutes + template.buffer_minutes <= window

    if payload.apply and not fits:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The planned route takes {plan.total_minutes} min, which with its "
                f"{template.buffer_minutes}-min buffer doesn't fit its {window}-min window. "
                "Widen the window or split the route."
            ),
        )
    if payload.apply:
        before = {
            "stops": [
                {"stop_id": rs.stop_id, "minutes_from_start": rs.minutes_from_start}
                for rs in template.stops
            ],
            "duration_minutes": template.duration_minutes,
        }
        template.stops.clear()
        db.flush()
        for s in planned:
            template.stops.append(
                RouteStop(
                    position=s.position,
                    stop_id=s.stop_id,
                    minutes_from_start=s.minutes_from_start,
                )
            )
        template.duration_minutes = max(1, plan.total_minutes)
        db.flush()
        record_audit(
            db,
            entity_type="route_template",
            entity_id=template.id,
            action="stops_planned",
            actor=current_user,
            before_state=before,
            after_state={
                "stops": [
                    {"stop_id": s.stop_id, "minutes_from_start": s.minutes_from_start}
                    for s in planned
                ],
                "duration_minutes": template.duration_minutes,
                "ride_limits_met": not violations,
            },
        )
        db.commit()

    return RoutePlanRead(
        stops=planned,
        total_minutes=plan.total_minutes,
        current_duration_minutes=current_duration,
        window_minutes=window,
        fits_window=fits,
        ride_limits_met=not violations,
        violations=violations,
        applied=payload.apply,
        travel_estimate=TRAVEL_ESTIMATE,
    )


def _route_or_404(db: Session, template_id: int) -> RouteTemplate:
    template = db.get(RouteTemplate, template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route template not found"
        )
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
    template_driver = db.get(Driver, payload.driver_id)
    if template_driver is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    template_vehicle = db.get(Vehicle, payload.vehicle_id)
    if template_vehicle is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown vehicle_id")
    unlicensed = license_violation(template_driver, template_vehicle)
    if unlicensed is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot create crew template: {unlicensed}",
        )

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
    unlicensed_template_ids: list[int] = []

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
        # A route that follows the bells takes that day's (an early-release
        # day moves it); otherwise, or with no bells set, its own window.
        earliest, latest = bells.template_window(db, rt, service_date) or (
            rt.window_earliest,
            rt.window_latest,
        )
        run = Run(
            service_date=service_date,
            school_id=rt.school_id,
            direction=rt.direction,
            window_earliest=earliest,
            window_latest=latest,
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
        if resource_unavailable_reason(ct.driver, ct.vehicle) is not None or any(
            # In maintenance (or past its inspection) the whole day: the
            # driver stays free to be paired with a spare bus instead.
            start <= ct.available_window_earliest and end >= ct.available_window_latest
            for start, end, _ in vehicle_blocks(db, ct.vehicle, service_date)
        ):
            out_of_service_template_ids.append(ct.id)
            continue
        if license_violation(ct.driver, ct.vehicle) is not None:
            unlicensed_template_ids.append(ct.id)
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
        crews_skipped_unlicensed_template_ids=unlicensed_template_ids,
    )
