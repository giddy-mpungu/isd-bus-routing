"""spec section 13 (driver absence + substitute coverage). Read-only
decision support only — spec section 13.1's "automatic coverage
analysis" identifies affected assignments and ranks substitute
candidates, but completing a substitution reuses existing endpoints,
not a new one: a candidate with no crew of their own that date is
substituted in via PATCH /crews/{id} (repoints the absent driver's own
crew — a vehicle already claimed by a crew row for a date can't be
paired with a second driver via POST /crews, its own uniqueness
constraint would reject that); a candidate who already has a different
crew that date is reassigned via the existing
PATCH /schedule/assignments/{id} instead (which already re-validates
every hard constraint). Spec section 21: decision support, not an
autonomous authority."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.availability import driver_conflict_for_window
from isd_api.db import get_db
from isd_api.licensing import license_violation
from isd_api.models import Assignment, Crew, Driver, DriverAbsence, Role, Run, User
from isd_api.routers.optimization_settings import load_min_rest_minutes, load_work_rules
from isd_api.schemas import (
    AbsenceCreate,
    AbsenceRead,
    AffectedAssignmentSubstitutes,
    SubstituteCandidate,
)
from isd_api.security import get_current_user, require_role
from isd_api.work_rules import day_problem, day_work, rest_problem

router = APIRouter(prefix="/drivers", tags=["absences"])
# Driver-agnostic listing ("who's out today") doesn't fit the /drivers
# prefix above — a separate router, registered alongside it in main.py.
all_absences_router = APIRouter(prefix="/absences", tags=["absences"])


@router.post(
    "/{driver_id}/absences", response_model=AbsenceRead, status_code=status.HTTP_201_CREATED
)
def create_absence(
    driver_id: int,
    payload: AbsenceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DriverAbsence:
    """spec section 13: "An absence may originate from: Driver
    application, Dispatcher, Supervisor, ..." — a driver can report
    their own absence, or transportation_admin/dispatcher can report
    for any driver (phone call, HR-reported, etc.)."""
    is_self = current_user.role == Role.DRIVER and current_user.driver_id == driver_id
    is_staff = current_user.role in (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)
    if not (is_self or is_staff):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only report your own absence",
        )
    if db.get(Driver, driver_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    if payload.start_minute > payload.end_minute:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_minute must be <= end_minute",
        )

    absence = DriverAbsence(
        driver_id=driver_id,
        service_date=payload.service_date,
        start_minute=payload.start_minute,
        end_minute=payload.end_minute,
        reason=payload.reason,
    )
    db.add(absence)
    db.flush()
    record_audit(
        db,
        entity_type="driver_absence",
        entity_id=absence.id,
        action="created",
        actor=current_user,
        after_state={
            "driver_id": driver_id,
            "service_date": str(payload.service_date),
            "reason": payload.reason.value,
        },
    )
    db.commit()
    db.refresh(absence)
    return absence


@router.get("/{driver_id}/absences", response_model=list[AbsenceRead])
def list_absences(
    driver_id: int,
    service_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[DriverAbsence]:
    return list(
        db.query(DriverAbsence)
        .filter(DriverAbsence.driver_id == driver_id, DriverAbsence.service_date == service_date)
        .order_by(DriverAbsence.id)
        .all()
    )


@all_absences_router.get("", response_model=list[AbsenceRead])
def list_all_absences(
    service_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[DriverAbsence]:
    """Who's out on a given date, across all drivers — the overview a
    dispatcher opening the console for a date needs; the per-driver
    GET /drivers/{id}/absences above only helps once you already
    suspect a specific driver is absent."""
    return list(
        db.query(DriverAbsence)
        .filter(DriverAbsence.service_date == service_date)
        .order_by(DriverAbsence.id)
        .all()
    )


def _rank_substitute_candidates(db: Session, assignment: Assignment) -> list[SubstituteCandidate]:
    """First-pass heuristic, not a final formula — spec section 13.1
    says "ranked according to factors such as," doesn't prescribe
    exact weights (section 2.2 already anticipates configurable
    objective weighting as a future admin setting).

    A candidate must be licensed (spec section 15) for the bus they'd
    drive: their own crew's bus that day if they have one, else the
    absent driver's bus, which they'd take over by a crew repoint. The
    other hard constraints (capacity, a run's required vehicle
    qualifications) are enforced when the chosen candidate is actually
    assigned, via the same checks every manual reassignment goes
    through."""
    rules = load_work_rules(db)
    min_rest = load_min_rest_minutes(db)
    absent_driver_id = assignment.crew.driver_id
    service_date = assignment.crew.service_date
    start, end = assignment.start_minute, assignment.end_minute

    candidates: list[SubstituteCandidate] = []
    for driver in db.query(Driver).filter(Driver.id != absent_driver_id).order_by(Driver.id):
        # Hard exclude: deactivated, or absent themselves during this run.
        if driver_conflict_for_window(db, driver, service_date, start, end) is not None:
            continue
        # Hard exclude: not licensed for the bus they'd be driving.
        own_crew = (
            db.query(Crew)
            .filter(Crew.driver_id == driver.id, Crew.service_date == service_date)
            .one_or_none()
        )
        bus = own_crew.vehicle if own_crew is not None else assignment.crew.vehicle
        if license_violation(driver, bus) is not None:
            continue
        same_day = (
            db.query(Assignment)
            .join(Crew, Assignment.crew_id == Crew.id)
            .filter(Crew.driver_id == driver.id, Crew.service_date == service_date)
            .all()
        )
        # Hard exclude: a genuine double-booking.
        if any(a.start_minute < end and start < a.end_minute for a in same_day):
            continue
        # Hard exclude: would break the driver's own duty limit or the
        # district's work-hour rules (isd_api/work_rules.py, the same rules
        # the solver keeps).
        work = day_work(db, driver.id, assignment.run.service_date)
        if day_problem([*work, (start, end)], driver.max_continuous_minutes, rules) or rest_problem(
            db, driver.id, assignment.run.service_date, start, end, min_rest
        ):
            continue

        score = 0
        reasons: list[str] = []

        # Spec section 13: route experience counts most, then the school.
        route_id = assignment.run.route_template_id
        on_route = (
            0
            if route_id is None
            else db.query(Assignment)
            .join(Crew, Assignment.crew_id == Crew.id)
            .join(Run, Assignment.run_id == Run.id)
            .filter(
                Crew.driver_id == driver.id,
                Run.route_template_id == route_id,
                Assignment.id != assignment.id,
            )
            .count()
        )
        if on_route > 0:
            score += 2 * on_route
            reasons.append(f"has driven this route {on_route} time(s) before")

        familiarity = (
            db.query(Assignment)
            .join(Crew, Assignment.crew_id == Crew.id)
            .join(Run, Assignment.run_id == Run.id)
            .filter(Crew.driver_id == driver.id, Run.school_id == assignment.run.school_id)
            .count()
        )
        if familiarity > 0:
            score += familiarity
            reasons.append(f"has driven this school {familiarity} time(s) before")

        if same_day:
            score -= len(same_day)
            reasons.append(f"already has {len(same_day)} other assignment(s) that day")

        if not reasons:
            reasons.append("available, no prior history at this school")

        candidates.append(
            SubstituteCandidate(
                driver_id=driver.id, full_name=driver.full_name, score=score, reasons=reasons
            )
        )

    candidates.sort(key=lambda c: (-c.score, c.driver_id))
    return candidates


@router.get(
    "/{driver_id}/substitute-candidates", response_model=list[AffectedAssignmentSubstitutes]
)
def get_substitute_candidates(
    driver_id: int,
    service_date: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[AffectedAssignmentSubstitutes]:
    """spec section 13.1: identifies this driver's affected assignments
    for the date and ranks substitutes for each — usable proactively,
    doesn't require a DriverAbsence row to already exist."""
    if db.get(Driver, driver_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    crew = (
        db.query(Crew)
        .filter(Crew.driver_id == driver_id, Crew.service_date == service_date)
        .one_or_none()
    )
    if crew is None:
        return []

    assignments = (
        db.query(Assignment)
        .filter(Assignment.crew_id == crew.id)
        .order_by(Assignment.start_minute)
        .all()
    )
    return [
        AffectedAssignmentSubstitutes(
            assignment_id=a.id,
            run_id=a.run_id,
            school_name=a.run.school.name,
            start_minute=a.start_minute,
            end_minute=a.end_minute,
            crew_id=crew.id,
            vehicle_id=crew.vehicle_id,
            vehicle_label=crew.vehicle.label,
            candidates=_rank_substitute_candidates(db, a),
        )
        for a in assignments
    ]
