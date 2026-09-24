"""spec section 3 (student/stop assignment) and section 4 (ridership
status). Phase 5 MVP: manual entry only (no SIS sync yet, ADR 0007's
explicit precedent) — a transportation admin creates Students and
links guardians; a student or their linked guardian(s) can then see
their own family's assignment and declare per-day, per-leg (AM/PM)
ridership overrides (section 4.2), which is the same mechanism as a
"late request to ride" (section 4.5)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import (
    Assignment,
    RideDirection,
    RidershipOverride,
    Role,
    Run,
    School,
    Stop,
    Student,
    User,
    VehiclePosition,
)
from isd_api.ridership_rules import change_closed_reason, load_rules
from isd_api.routers.runs import _resolve_riding_students
from isd_api.schemas import (
    BusPositionRead,
    FamilyMemberRead,
    GuardianLink,
    GuardianRead,
    RidershipOverrideUpdate,
    StudentCreate,
    StudentRead,
    StudentUpdate,
)
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/students", tags=["students"])

# Family-facing bus positions are rounded to this many decimal places (~100 m).
APPROXIMATE_POSITION_DECIMALS = 3


@router.post("", response_model=StudentRead, status_code=status.HTTP_201_CREATED)
def create_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Student:
    student = Student(
        full_name=payload.full_name,
        school_id=payload.school_id,
        stop_id=payload.stop_id,
        default_ridership=payload.default_ridership,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


@router.get("", response_model=list[StudentRead])
def list_students(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)),
) -> list[Student]:
    return list(db.query(Student).order_by(Student.id).all())


@router.patch("/{student_id}", response_model=StudentRead)
def update_student(
    student_id: int,
    payload: StudentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Student:
    """Spec section 21 "reassign students": name, school, stop, default
    ridership. Audited, since a school or stop change changes which bus a
    child is expected on."""
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    sent = payload.model_fields_set

    sis_owned = {"full_name", "school_id"} & sent
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

    fields = ("full_name", "school_id", "stop_id", "default_ridership")
    before = {f: _plain(getattr(student, f)) for f in fields}
    if "full_name" in sent and payload.full_name is not None:
        student.full_name = payload.full_name
    if "school_id" in sent and payload.school_id is not None:
        student.school_id = payload.school_id
    if "stop_id" in sent:
        student.stop_id = payload.stop_id
    if "default_ridership" in sent and payload.default_ridership is not None:
        student.default_ridership = payload.default_ridership
    db.flush()
    after = {f: _plain(getattr(student, f)) for f in fields}
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
    return student


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
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> list[GuardianRead]:
    student = _student_or_404(db, student_id)
    return [
        GuardianRead(user_id=g.id, full_name=g.full_name, email=g.email)
        for g in sorted(student.guardians, key=lambda g: g.full_name)
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


@router.get("/my-family", response_model=list[FamilyMemberRead])
def get_my_family(
    service_date: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.STUDENT, Role.PARENT)),
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
    return [
        FamilyMemberRead(
            student_id=s.id,
            full_name=s.full_name,
            school_name=s.school.name,
            stop_label=s.stop.label if s.stop is not None else None,
            service_date=service_date,
            riding_am=overrides.get((s.id, RideDirection.AM), default_riding[s.id]),
            riding_pm=overrides.get((s.id, RideDirection.PM), default_riding[s.id]),
            am_changes_closed=am_closed,
            pm_changes_closed=pm_closed,
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

    runs = (
        db.query(Run)
        .filter(
            Run.school_id == student.school_id,
            Run.service_date == service_date,
            Run.direction == direction,
        )
        .all()
    )
    if len(runs) == 0:
        return BusPositionRead(available=False, ambiguous=False)
    if len(runs) > 1:
        return BusPositionRead(available=False, ambiguous=True)

    assignment = db.query(Assignment).filter(Assignment.run_id == runs[0].id).one_or_none()
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


def _bus_full_reason(
    db: Session, student: Student, service_date: date, direction: RideDirection
) -> str | None:
    """Spec section 4.5: a request to ride needs room on the bus. Checked
    only when exactly one run serves this school, date and leg and it has
    a bus assigned; with several runs the rider can't be attributed to one
    bus (the same "don't guess" rule as the expected-riders count)."""
    runs = (
        db.query(Run)
        .filter(
            Run.school_id == student.school_id,
            Run.service_date == service_date,
            Run.direction == direction,
        )
        .all()
    )
    if len(runs) != 1 or runs[0].assignment is None:
        return None
    riders, ambiguous = _resolve_riding_students(db, runs[0])
    if ambiguous or student in riders:
        return None
    capacity = runs[0].assignment.crew.vehicle.allowable_capacity()
    if capacity is None or len(riders) < capacity:
        return None
    return (
        f"The {direction.value.upper()} bus for {student.school.name} on {service_date} is full "
        f"({len(riders)} of {capacity} seats). Please contact the transportation office."
    )


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
