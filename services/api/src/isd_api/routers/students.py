"""spec section 3 (student/stop assignment) and section 4 (ridership
status). Phase 5 MVP: manual entry only (no SIS sync yet, ADR 0007's
explicit precedent) — a transportation admin creates Students and
links guardians; a student or their linked guardian(s) can then see
their own family's assignment and declare per-day, per-leg (AM/PM)
ridership overrides (section 4.2), which is the same mechanism as a
"late request to ride" (section 4.5)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from isd_api import (
    access_log,
    account_emails,
    eligibility,
    i18n,
    mailer,
    retention,
    student_records,
)
from isd_api.audit import record as record_audit
from isd_api.daily_trip import daily_trip
from isd_api.db import get_db
from isd_api.integrations import census_geocoder
from isd_api.models import (
    Assignment,
    GeocodeSource,
    RideDirection,
    RidershipDefault,
    RidershipOverride,
    Role,
    School,
    Stop,
    Student,
    StudentAccess,
    StudentHome,
    User,
    VehiclePosition,
)
from isd_api.ridership_rules import change_closed_reason, district_now, load_rules
from isd_api.routers.runs import _resolve_riding_students
from isd_api.routers.vehicles import _resolve_qualifications
from isd_api.routes import leg_runs, route_stop_ids, run_for_student
from isd_api.schemas import (
    BusPositionRead,
    EligibilityRead,
    FamilyMemberRead,
    GuardianLink,
    GuardianRead,
    QualificationRead,
    RidershipOverrideUpdate,
    StopEtaRead,
    StudentAccessRead,
    StudentCreate,
    StudentHomeRead,
    StudentHomeUpdate,
    StudentRead,
    StudentUpdate,
    StudentWithdraw,
)
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/students", tags=["students"])

# Family-facing bus positions are rounded to this many decimal places (~100 m).
APPROXIMATE_POSITION_DECIMALS = 3


def _student_read(
    student: Student, home: StudentHome | None, rules: eligibility.Rules
) -> StudentRead:
    result = eligibility.eligibility_for(student, home, rules)
    return StudentRead(
        id=student.id,
        full_name=student.full_name,
        school_id=student.school_id,
        external_id=student.external_id,
        stop_id=student.stop_id,
        default_ridership=student.default_ridership,
        grade=student.grade,
        needs_specialized_transport=student.needs_specialized_transport,
        hazardous_route=student.hazardous_route,
        accommodations=[QualificationRead.model_validate(q) for q in student.accommodations],
        has_home=home is not None,
        withdrawn_on=student.withdrawn_on,
        delete_after=(
            retention.delete_after(student.withdrawn_on) if student.withdrawn_on else None
        ),
        eligibility=EligibilityRead(
            eligible=result.eligible,
            reason=result.reason,
            miles_from_school=result.miles_from_school,
            band=result.band,
        ),
    )


def _read_one(db: Session, student: Student) -> StudentRead:
    return _student_read(student, db.get(StudentHome, student.id), eligibility.load_rules(db))


@router.post("", response_model=StudentRead, status_code=status.HTTP_201_CREATED)
def create_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> StudentRead:
    student = Student(
        full_name=payload.full_name,
        school_id=payload.school_id,
        stop_id=payload.stop_id,
        default_ridership=payload.default_ridership,
        grade=payload.grade,
        needs_specialized_transport=payload.needs_specialized_transport,
        hazardous_route=payload.hazardous_route,
        accommodations=_resolve_qualifications(db, payload.accommodation_codes),
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return _read_one(db, student)


@router.get("", response_model=list[StudentRead])
def list_students(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[StudentRead]:
    """Dispatchers see each student's eligibility and distance band, never
    their home."""
    rules = eligibility.load_rules(db)
    homes = {h.student_id: h for h in db.query(StudentHome)}
    reads = [
        _student_read(s, homes.get(s.id), rules)
        for s in db.query(Student).order_by(Student.id).all()
    ]
    access_log.record_views(db, current_user, (r.id for r in reads), "list")
    return reads


@router.patch("/{student_id}", response_model=StudentRead)
def update_student(
    student_id: int,
    payload: StudentUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> StudentRead:
    """Spec section 21 "reassign students": name, school, stop, default
    ridership, plus grade, specialized transportation, the hazardous-route
    override and accommodations (spec section 3). Audited, since each can
    change which bus a child is expected on, or whether they get one."""
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    sent = payload.model_fields_set

    sis_owned = {"full_name", "school_id", "grade"} & sent
    if student.external_id is not None and sis_owned:
        changed = [
            f
            for f in sorted(sis_owned)
            if getattr(payload, f) is not None and getattr(payload, f) != getattr(student, f)
        ]
        if changed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{', '.join(changed)} for this student come from the SIS roster import; "
                    "change them in the SIS and re-import."
                ),
            )
    if "school_id" in sent and (
        payload.school_id is None or db.get(School, payload.school_id) is None
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")
    if "stop_id" in sent and payload.stop_id is not None and db.get(Stop, payload.stop_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown stop_id")
    if "full_name" in sent and payload.full_name is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="full_name is required")

    fields = (
        "full_name",
        "school_id",
        "stop_id",
        "default_ridership",
        "grade",
        "needs_specialized_transport",
        "hazardous_route",
    )

    def snapshot() -> dict:
        state = {f: _plain(getattr(student, f)) for f in fields}
        state["accommodations"] = sorted(q.code for q in student.accommodations)
        return state

    before = snapshot()
    if "full_name" in sent and payload.full_name is not None:
        student.full_name = payload.full_name
    if "school_id" in sent and payload.school_id is not None:
        student.school_id = payload.school_id
    if "stop_id" in sent:
        student.stop_id = payload.stop_id
    if "default_ridership" in sent and payload.default_ridership is not None:
        student.default_ridership = payload.default_ridership
    if "grade" in sent:
        student.grade = payload.grade
    for flag in ("needs_specialized_transport", "hazardous_route"):
        if flag in sent and getattr(payload, flag) is not None:
            setattr(student, flag, getattr(payload, flag))
    if "accommodation_codes" in sent and payload.accommodation_codes is not None:
        student.accommodations = _resolve_qualifications(db, payload.accommodation_codes)
    db.flush()
    after = snapshot()
    if after != before:
        record_audit(
            db,
            entity_type="student",
            entity_id=student.id,
            action="updated",
            actor=current_user,
            before_state=before,
            after_state=after,
        )
    db.commit()
    db.refresh(student)
    if after["stop_id"] != before["stop_id"] and mailer.is_configured():
        for email in account_emails.stop_change_emails(student):
            background.add_task(mailer.send_quietly, email)
    return _read_one(db, student)


# --- Home location (spec section 3): transportation admins only ------------


def _home_audit(
    db: Session, student: Student, action: str, actor: User, source: str | None
) -> None:
    # That it changed and how, never the address or the coordinates: audit
    # rows can't be deleted, and a home address is personal data.
    record_audit(
        db,
        entity_type="student_home",
        entity_id=student.id,
        action=action,
        actor=actor,
        after_state=None if source is None else {"source": source},
    )


@router.get("/{student_id}/home", response_model=StudentHomeRead)
def get_student_home(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> StudentHome:
    _student_or_404(db, student_id)
    home = db.get(StudentHome, student_id)
    if home is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No home on file")
    access_log.record_views(db, current_user, [student_id], "home")
    return home


@router.put("/{student_id}/home", response_model=StudentHomeRead)
def set_student_home(
    student_id: int,
    payload: StudentHomeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> StudentHome:
    """With just an address, looks it up with the US Census geocoder. With
    coordinates too, uses them as placed by hand on the map (for an address
    the Census can't find, or a match that's in the wrong place)."""
    student = _student_or_404(db, student_id)
    address = payload.address.strip()
    if payload.location_lat is not None and payload.location_lon is not None:
        lat, lon = payload.location_lat, payload.location_lon
        source, matched = GeocodeSource.MANUAL, None
    else:
        try:
            match = census_geocoder.geocode(address)
        except census_geocoder.GeocoderUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The Census address lookup isn't reachable right now. "
                "Try again, or place the home on the map.",
            ) from None
        if match is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The Census geocoder couldn't find that address. "
                "Check it, or place the home on the map.",
            )
        lat, lon = match.lat, match.lon
        source, matched = GeocodeSource.CENSUS, match.matched_address

    home = db.get(StudentHome, student_id)
    if home is None:
        home = StudentHome(student_id=student.id)
        db.add(home)
    home.address = address
    home.location_lat, home.location_lon = lat, lon
    home.source, home.matched_address = source, matched
    db.flush()
    _home_audit(db, student, "home_set", current_user, source.value)
    db.commit()
    db.refresh(home)
    return home


@router.delete("/{student_id}/home", status_code=status.HTTP_204_NO_CONTENT)
def delete_student_home(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> None:
    student = _student_or_404(db, student_id)
    home = db.get(StudentHome, student_id)
    if home is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No home on file")
    db.delete(home)
    db.flush()
    _home_audit(db, student, "home_removed", current_user, None)
    db.commit()


def _plain(value: object) -> object:
    return value.value if hasattr(value, "value") else value


def _student_or_404(db: Session, student_id: int) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return student


@router.get("/{student_id}/guardians", response_model=list[GuardianRead])
def list_guardians(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> list[GuardianRead]:
    student = _student_or_404(db, student_id)
    guardians = [
        GuardianRead(user_id=g.id, full_name=g.full_name, email=g.email)
        for g in sorted(student.guardians, key=lambda g: g.full_name)
    ]
    access_log.record_views(db, current_user, [student_id], "guardians")
    return guardians


@router.get("/{student_id}/access-log", response_model=list[StudentAccessRead])
def student_access_log(
    student_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> list[StudentAccessRead]:
    """FERPA: who at the district saw this student's information, newest
    first (isd_api/access_log.py). Viewing this list isn't itself logged."""
    _student_or_404(db, student_id)
    rows = (
        db.query(StudentAccess, User)
        .join(User, StudentAccess.user_id == User.id)
        .filter(StudentAccess.student_id == student_id)
        .order_by(StudentAccess.first_at.desc(), StudentAccess.id.desc())
        .limit(1000)
        .all()
    )
    return [
        StudentAccessRead(
            day=a.day,
            first_at=a.first_at,
            user_id=u.id,
            user_name=u.full_name,
            user_role=u.role,
            what=a.what,
            what_label=access_log.WHAT.get(a.what, a.what),
        )
        for a, u in rows
    ]


@router.post("/{student_id}/guardians", status_code=status.HTTP_204_NO_CONTENT)
def link_guardian(
    student_id: int,
    payload: GuardianLink,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> None:
    """A guardian link is what grants a parent access to a child's data
    (spec section 18), so every link and unlink is audited."""
    student = _student_or_404(db, student_id)
    guardian = db.get(User, payload.user_id)
    if guardian is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if guardian.role != Role.PARENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User {guardian.id} does not have the parent role",
        )
    if guardian not in student.guardians:
        student.guardians.append(guardian)
        db.flush()
        record_audit(
            db,
            entity_type="student",
            entity_id=student.id,
            action="guardian_linked",
            actor=current_user,
            after_state={"guardian_user_id": guardian.id},
        )
        db.commit()


@router.delete("/{student_id}/guardians/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_guardian(
    student_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> None:
    student = _student_or_404(db, student_id)
    guardian = next((g for g in student.guardians if g.id == user_id), None)
    if guardian is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That user is not a guardian of this student",
        )
    student.guardians.remove(guardian)
    db.flush()
    record_audit(
        db,
        entity_type="student",
        entity_id=student.id,
        action="guardian_unlinked",
        actor=current_user,
        before_state={"guardian_user_id": guardian.id},
    )
    db.commit()


def _linked_students(db: Session, current_user: User) -> list[Student]:
    """Every student this user is authorized to see or act on (spec
    section 18: never another family's data). A student sees only
    themself; a parent sees every student they're linked to via
    student_guardians."""
    if current_user.role == Role.STUDENT:
        if current_user.student_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This student account is not linked to a Student record",
            )
        student = db.get(Student, current_user.student_id)
        return [student] if student is not None else []
    if current_user.role == Role.PARENT:
        return list(current_user.guardian_of)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Role '{current_user.role.value}' cannot access family data",
    )


@router.post("/{student_id}/withdraw", response_model=StudentRead)
def withdraw_student(
    student_id: int,
    payload: StudentWithdraw,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> StudentRead:
    """FERPA (isd_api/retention.py): the student has left the district. They
    stop riding from that day; their personal data is deleted after the end
    of the following school year. Reinstate undoes it until then."""
    student = _student_or_404(db, student_id)
    on = payload.withdrawn_on or district_now(load_rules(db)).date()
    before = student.withdrawn_on
    student.withdrawn_on = on
    record_audit(
        db,
        entity_type="student",
        entity_id=student.id,
        action="withdrawn",
        actor=current_user,
        before_state={"withdrawn_on": before.isoformat() if before else None},
        after_state={
            "withdrawn_on": on.isoformat(),
            "delete_after": retention.delete_after(on).isoformat(),
        },
    )
    db.commit()
    return _read_one(db, student)


@router.post("/{student_id}/reinstate", response_model=StudentRead)
def reinstate_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> StudentRead:
    """Back in the district: no longer withdrawn, nothing to delete."""
    student = _student_or_404(db, student_id)
    if student.withdrawn_on is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not withdrawn")
    before = student.withdrawn_on
    student.withdrawn_on = None
    record_audit(
        db,
        entity_type="student",
        entity_id=student.id,
        action="reinstated",
        actor=current_user,
        before_state={"withdrawn_on": before.isoformat()},
    )
    db.commit()
    return _read_one(db, student)


@router.get("/{student_id}/records", response_class=HTMLResponse)
def download_records(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(Role.PARENT, Role.STUDENT, Role.TRANSPORTATION_ADMIN)
    ),
    asked_language: str = Depends(i18n.request_language),
) -> HTMLResponse:
    """FERPA's right to inspect and review (isd_api/student_records.py):
    everything held about a student, as a file. A parent for their own
    child, a student for themself, a transportation admin for anyone
    (for a request made another way). Every download is audited."""
    student = _student_or_404(db, student_id)
    if current_user.role != Role.TRANSPORTATION_ADMIN and student not in _linked_students(
        db, current_user
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    now = datetime.now(UTC)
    # A plain link, so the browser's language unless they chose one here.
    lang = i18n.normalize(current_user.preferred_language or asked_language)
    page = student_records.build(db, student, now, lang)
    record_audit(
        db,
        entity_type="student",
        entity_id=student.id,
        action="records_downloaded",
        actor=current_user,
    )
    db.commit()
    access_log.record_views(db, current_user, [student.id], "records")
    filename = f"transportation-records-{student.id}-{now.date().isoformat()}.html"
    return HTMLResponse(
        page,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/my-family", response_model=list[FamilyMemberRead])
def get_my_family(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.STUDENT, Role.PARENT)),
    lang: str = Depends(i18n.request_language),
) -> list[FamilyMemberRead]:
    students = _linked_students(db, current_user)
    overrides = {
        (o.student_id, o.direction): o.is_riding
        for o in db.query(RidershipOverride)
        .filter(
            RidershipOverride.student_id.in_([s.id for s in students]),
            RidershipOverride.service_date == service_date,
        )
        .all()
    }
    default_riding = {s.id: s.default_ridership.value == "rides" for s in students}
    rules = load_rules(db)
    am_closed = change_closed_reason(rules, service_date, RideDirection.AM)
    pm_closed = change_closed_reason(rules, service_date, RideDirection.PM)
    if am_closed is not None:
        am_closed = i18n.translate_message(lang, am_closed)
    if pm_closed is not None:
        pm_closed = i18n.translate_message(lang, pm_closed)

    def riding(s: Student, direction: RideDirection) -> bool:
        return overrides.get((s.id, direction), default_riding[s.id])

    def eta(s: Student, direction: RideDirection) -> StopEtaRead | None:
        """Today's estimated arrival at this child's stop, or None."""
        if not riding(s, direction) or s.stop_id is None:
            return None
        run, ambiguous = run_for_student(db, s, service_date, direction)
        if ambiguous or run is None or run.assignment is None:
            return None
        trip = daily_trip(db, run, run.assignment.start_minute)
        stop = next((t for t in trip or [] if t.stop_id == s.stop_id), None)
        if stop is None or stop.eta_minute is None:
            return None
        return StopEtaRead(
            stop_label=stop.label,
            eta_minute=stop.eta_minute,
            planned_minute=stop.planned_minute,
            changed=stop.materially_changed,
        )

    return [
        FamilyMemberRead(
            student_id=s.id,
            full_name=s.full_name,
            school_name=s.school.name,
            stop_label=s.stop.label if s.stop is not None else None,
            service_date=service_date,
            riding_am=riding(s, RideDirection.AM),
            riding_pm=riding(s, RideDirection.PM),
            am_changes_closed=am_closed,
            pm_changes_closed=pm_closed,
            am_eta=eta(s, RideDirection.AM),
            pm_eta=eta(s, RideDirection.PM),
        )
        for s in students
    ]


@router.get("/{student_id}/bus-position", response_model=BusPositionRead)
def get_bus_position(
    student_id: int,
    service_date: date,
    direction: RideDirection,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.STUDENT, Role.PARENT)),
) -> BusPositionRead:
    """spec section 18: "approximate bus location" for one child's leg.
    See BusPositionRead's docstring for the available/ambiguous shape --
    this deliberately never guesses which bus is "the" bus when more
    than one run could serve this leg (same gap PR #23 named for
    expected-riders)."""
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    is_self = current_user.role == Role.STUDENT and current_user.student_id == student_id
    is_guardian = current_user.role == Role.PARENT and student in current_user.guardian_of
    if not (is_self or is_guardian):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own family's bus position",
        )

    # With several runs on this leg, the one whose route has the child's
    # stop (isd_api/routes.py); still never a guess.
    run, ambiguous = run_for_student(db, student, service_date, direction)
    if ambiguous:
        return BusPositionRead(available=False, ambiguous=True)
    if run is None:
        return BusPositionRead(available=False, ambiguous=False)

    assignment = db.query(Assignment).filter(Assignment.run_id == run.id).one_or_none()
    if assignment is None:
        return BusPositionRead(available=False, ambiguous=False)
    position = (
        db.query(VehiclePosition)
        .filter(VehiclePosition.crew_id == assignment.crew_id)
        .one_or_none()
    )
    if position is None:
        return BusPositionRead(available=False, ambiguous=False)

    # Spec section 18: an *approximate* location and no driver identity.
    # Three decimal places is roughly 100 m, enough to see where the bus
    # is without making the family app a precise tracker.
    return BusPositionRead(
        available=True,
        ambiguous=False,
        location_lat=round(position.location_lat, APPROXIMATE_POSITION_DECIMALS),
        location_lon=round(position.location_lon, APPROXIMATE_POSITION_DECIMALS),
        recorded_at=position.recorded_at,
        vehicle_label=position.crew.vehicle.label,
    )


BUS_FULL = (
    "The {leg} bus for {school} on {date} is full ({riders} of {capacity} seats). "
    "Please contact the transportation office."
)


def _bus_full_reason(
    db: Session, student: Student, service_date: date, direction: RideDirection
) -> str | None:
    """Spec section 4.5: a request to ride needs room on the bus. Checked
    when the student's run is known (one run on the leg, or the one whose
    route has their stop) and it has a bus assigned; otherwise the rider
    can't be attributed to one bus (the "don't guess" rule)."""
    run, ambiguous = run_for_student(db, student, service_date, direction)
    if ambiguous or run is None or run.assignment is None:
        return None
    riders, ambiguous = _resolve_riding_students(db, run)
    if ambiguous or student in riders:
        return None
    capacity = run.assignment.crew.vehicle.allowable_capacity()
    if capacity is None or len(riders) < capacity:
        return None
    return BUS_FULL.format(
        leg=direction.value.upper(),
        school=student.school.name,
        date=service_date,
        riders=len(riders),
        capacity=capacity,
    )


NOT_ELIGIBLE = (
    "{name} lives under {limit} mi from school, so isn't eligible for the bus. "
    "Please contact the transportation office."
)
NO_STOP = "{name} has no bus stop yet. Please contact the transportation office."
STOP_NOT_ON_ROUTE = (
    "{name}'s stop, {stop}, isn't on the {leg} route on {date}. "
    "Please contact the transportation office."
)


def _late_request_problem(
    db: Session, student: Student, service_date: date, direction: RideDirection
) -> str | None:
    """Spec section 4.5's other two checks on a family's request to ride
    for a student who doesn't usually: eligibility, refused only when a
    home on file shows them under the distance (without one it can't be
    told), and a stop that day's route serves, checked when every route
    on the leg has a stop list (otherwise the stop may still be served)."""
    home = db.get(StudentHome, student.id)
    if home is not None:
        rules = eligibility.load_rules(db)
        if not eligibility.eligibility_for(student, home, rules).eligible:
            return NOT_ELIGIBLE.format(name=student.full_name, limit=f"{rules.eligibility_miles:g}")
    if student.stop_id is None or student.stop is None:
        return NO_STOP.format(name=student.full_name)
    stop_lists = [
        route_stop_ids(db, r) for r in leg_runs(db, student.school_id, service_date, direction)
    ]
    if stop_lists and all(stop_lists) and not any(student.stop_id in ids for ids in stop_lists):
        return STOP_NOT_ON_ROUTE.format(
            name=student.full_name,
            stop=student.stop.label,
            leg=direction.value.upper(),
            date=service_date,
        )
    return None


@router.patch("/{student_id}/ridership", status_code=status.HTTP_204_NO_CONTENT)
def update_ridership(
    student_id: int,
    payload: RidershipOverrideUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """spec section 4.2 daily override, and section 4.5's "late request
    to ride" — the same upsert covers both (flipping a Does-Not-Ride
    default's override to is_riding=True for one day *is* a late
    request; no separate flow needed at this scope). Allowed: the
    student themself, a linked guardian, or a transportation_admin
    (covers a phone-in request from a family without an account)."""
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    is_self = current_user.role == Role.STUDENT and current_user.student_id == student_id
    is_guardian = current_user.role == Role.PARENT and student in current_user.guardian_of
    is_admin = current_user.role == Role.TRANSPORTATION_ADMIN
    if not (is_self or is_guardian or is_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only declare ridership for your own family",
        )

    # Spec section 4.4: families can't change a past day, or today after the
    # district's cutoff for that leg. Staff can (a phone-in, spec section 21).
    if not is_admin:
        closed = change_closed_reason(load_rules(db), payload.service_date, payload.direction)
        if closed is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=closed)
    if payload.is_riding and not is_admin and student.default_ridership != RidershipDefault.RIDES:
        problem = _late_request_problem(db, student, payload.service_date, payload.direction)
        if problem is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=problem)
    if payload.is_riding:
        full = _bus_full_reason(db, student, payload.service_date, payload.direction)
        if full is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=full)

    existing = (
        db.query(RidershipOverride)
        .filter(
            RidershipOverride.student_id == student_id,
            RidershipOverride.service_date == payload.service_date,
            RidershipOverride.direction == payload.direction,
        )
        .one_or_none()
    )
    if existing is not None:
        existing.is_riding = payload.is_riding
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(
            RidershipOverride(
                student_id=student_id,
                service_date=payload.service_date,
                direction=payload.direction,
                is_riding=payload.is_riding,
            )
        )
    db.commit()
