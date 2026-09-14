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

from isd_api.db import get_db
from isd_api.models import (
    Assignment,
    RideDirection,
    RidershipOverride,
    Role,
    Run,
    Student,
    User,
    VehiclePosition,
)
from isd_api.schemas import (
    BusPositionRead,
    FamilyMemberRead,
    GuardianLink,
    RidershipOverrideUpdate,
    StudentCreate,
    StudentRead,
    StudentUpdate,
)
from isd_api.security import get_current_user, require_role

router = APIRouter(prefix="/students", tags=["students"])


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
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> Student:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    if payload.stop_id is not None:
        student.stop_id = payload.stop_id
    if payload.default_ridership is not None:
        student.default_ridership = payload.default_ridership
    db.commit()
    db.refresh(student)
    return student


@router.post("/{student_id}/guardians", status_code=status.HTTP_204_NO_CONTENT)
def link_guardian(
    student_id: int,
    payload: GuardianLink,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> None:
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
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
    return [
        FamilyMemberRead(
            student_id=s.id,
            full_name=s.full_name,
            school_name=s.school.name,
            stop_label=s.stop.label if s.stop is not None else None,
            service_date=service_date,
            riding_am=overrides.get((s.id, RideDirection.AM), default_riding[s.id]),
            riding_pm=overrides.get((s.id, RideDirection.PM), default_riding[s.id]),
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

    return BusPositionRead(
        available=True,
        ambiguous=False,
        location_lat=position.location_lat,
        location_lon=position.location_lon,
        recorded_at=position.recorded_at,
        driver_full_name=position.crew.driver.full_name,
        vehicle_label=position.crew.vehicle.label,
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
