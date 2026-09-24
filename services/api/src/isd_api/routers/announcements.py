"""spec sections 9/18: notices for drivers and/or families. See
models.Announcement's docstring for the human-authored-vs-one-
auto-generated-exception design and the school-scoping rule."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import (
    Announcement,
    AnnouncementAudience,
    AnnouncementCategory,
    Assignment,
    Crew,
    Role,
    Run,
    School,
    Student,
    User,
)
from isd_api.schemas import AnnouncementCreate, AnnouncementRead
from isd_api.security import require_role

router = APIRouter(prefix="/announcements", tags=["announcements"])

_WRITE_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)
_RECIPIENT_ROLES = (Role.DRIVER, Role.STUDENT, Role.PARENT, Role.SCHOOL_ADMIN)


def _recipient_school_ids(db: Session, current_user: User) -> set[int]:
    """Schools relevant to this non-driver recipient -- used to filter
    school-scoped FAMILY-audience announcements down to the ones that
    actually concern them. Empty set for a student account with no
    linked record, a parent with none linked yet, or a school_admin
    account not linked to a school; that's not an error here (unlike
    routers/students.py's _linked_students) since district-wide
    announcements should still come through regardless.

    spec section 17: school_admin's own access list names "transportation
    notices" for their school specifically -- reusing FAMILY-audience
    scoping is the closest fit, since there's no separate audience
    value for school staff and the actual content (delays,
    substitutions, route changes for that school) is the same thing a
    parent at that school would see."""
    if current_user.role == Role.STUDENT:
        if current_user.student_id is None:
            return set()
        student = db.get(Student, current_user.student_id)
        return {student.school_id} if student is not None else set()
    if current_user.role == Role.SCHOOL_ADMIN:
        return {current_user.school_id} if current_user.school_id is not None else set()
    return {s.school_id for s in current_user.guardian_of}


@router.post("", response_model=AnnouncementRead, status_code=status.HTTP_201_CREATED)
def create_announcement(
    payload: AnnouncementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_WRITE_ROLES)),
) -> Announcement:
    if payload.school_id is not None and db.get(School, payload.school_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")
    announcement = Announcement(
        message=payload.message,
        category=payload.category,
        audience=payload.audience,
        school_id=payload.school_id,
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
            "school_id": announcement.school_id,
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
    audience (and, for families, their own school)."""
    return list(db.query(Announcement).order_by(Announcement.created_at.desc()).all())


@router.get("/mine", response_model=list[AnnouncementRead])
def list_my_announcements(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_RECIPIENT_ROLES)),
) -> list[Announcement]:
    if current_user.role == Role.DRIVER:
        # school_id scoping isn't meaningful for a driver -- see
        # models.Announcement's docstring.
        return list(
            db.query(Announcement)
            .filter(
                Announcement.audience.in_([AnnouncementAudience.ALL, AnnouncementAudience.DRIVER])
            )
            .order_by(Announcement.created_at.desc())
            .all()
        )
    # STUDENT/PARENT/SCHOOL_ADMIN all read the same FAMILY-audience
    # feed, filtered to schools relevant to each -- see
    # _recipient_school_ids's docstring for school_admin's inclusion.
    school_ids = _recipient_school_ids(db, current_user)
    announcements = (
        db.query(Announcement)
        .filter(Announcement.audience.in_([AnnouncementAudience.ALL, AnnouncementAudience.FAMILY]))
        .order_by(Announcement.created_at.desc())
        .all()
    )
    return [a for a in announcements if a.school_id is None or a.school_id in school_ids]


def _maybe_create_substitution_announcement(db: Session, crew: Crew, actor: User) -> None:
    """spec section 13's driver/vehicle swap -> spec section 18's "Bus
    substitution notices" -- the one case models.Announcement's
    docstring names as auto-generated, and only when it can be done
    without guessing. Called after a crew's driver or vehicle actually
    changes on an already-solved day (routers/crews.py's
    update_crew_driver, routers/schedule.py's update_assignment); a
    crew with no assignments yet (schedule not solved, or this is
    day-of-week setup rather than a real substitution) has nothing to
    loop over and this is a no-op.

    For each distinct (school, direction) this crew serves that day,
    skips if more than one Run shares that school/date/direction --
    the same "don't guess which run/family is actually affected" rule
    PR #23's expected-riders and GET /students/{id}/bus-position
    already established. Never raises; a partial/no announcement is
    fine, this is a courtesy, not a blocking prerequisite for the
    reassignment it followed."""
    assignments = db.query(Assignment).filter(Assignment.crew_id == crew.id).all()
    seen: set[tuple[int, str]] = set()
    for assignment in assignments:
        run = assignment.run
        key = (run.school_id, run.direction.value)
        if key in seen:
            continue
        seen.add(key)
        other_runs = (
            db.query(Run)
            .filter(
                Run.school_id == run.school_id,
                Run.service_date == run.service_date,
                Run.direction == run.direction,
                Run.id != run.id,
            )
            .count()
        )
        if other_runs > 0:
            continue

        # Family-facing, so no driver identity (spec section 18: never
        # reveal driver personal information). The bus is what they need.
        message = (
            f"{run.school.name}: the {run.direction.value.upper()} run on "
            f"{run.service_date} will be covered by a substitute. Look for {crew.vehicle.label}."
        )
        announcement = Announcement(
            message=message,
            category=AnnouncementCategory.SUBSTITUTION,
            audience=AnnouncementAudience.FAMILY,
            school_id=run.school_id,
        )
        db.add(announcement)
        db.flush()
        record_audit(
            db,
            entity_type="announcement",
            entity_id=announcement.id,
            action="created",
            actor=actor,
            after_state={
                "message": announcement.message,
                "category": announcement.category.value,
                "audience": announcement.audience.value,
                "school_id": announcement.school_id,
                "auto_generated_from_run_id": run.id,
            },
        )
