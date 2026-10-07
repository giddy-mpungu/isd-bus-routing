"""Deleting the personal data of students who have left (FERPA, Phase 5).

Decided by the product owner on 2026-10-07: once a transportation admin
marks a student withdrawn (`Student.withdrawn_on`), their data is kept
through the end of the following school year, for questions about past
rides, then deleted automatically. School years end on
`ISD_API_SCHOOL_YEAR_END` (06-30); withdrawn on 2026-10-07 (school year
2026-27) means deleted after 2028-06-30.

What goes: the student, their home address, ridership changes, guardian
and accommodation links, bus-time email records, the access log, their
correction requests, their place in stop proposals; a student login is
anonymised and switched off; the student's audit entries keep their dates,
actions and actors but lose the before/after values (names, addresses).
One `deleted_after_retention` audit entry records that it happened.
Run daily by the worker (isd_api/worker.py).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from isd_api.audit import record as record_audit
from isd_api.config import settings
from isd_api.models import (
    AuditLogEntry,
    EtaNotification,
    RecordCorrection,
    RidershipOverride,
    StopProposal,
    Student,
    StudentAccess,
    StudentHome,
    User,
)
from isd_api.ridership_rules import district_now, load_rules, utc_now
from isd_api.security import UNUSABLE_PASSWORD


def _school_year_end(on: date) -> date:
    """The last day of the school year `on` falls in."""
    month, day = (int(p) for p in settings.school_year_end.split("-"))
    end = date(on.year, month, day)
    return end if on <= end else date(on.year + 1, month, day)


def delete_after(withdrawn_on: date) -> date:
    """The last day a withdrawn student's data is kept."""
    end = _school_year_end(withdrawn_on)
    return end.replace(year=end.year + settings.student_retention_school_years)


def purge(db: Session, student: Student) -> None:
    """Deletes one student's personal data (see the module docstring).
    The caller commits."""
    sid = student.id
    for model in (StudentHome, RidershipOverride, EtaNotification, StudentAccess, RecordCorrection):
        db.query(model).filter(model.student_id == sid).delete(synchronize_session=False)
    student.guardians = []
    student.accommodations = []
    for proposal in db.query(StopProposal).all():
        if proposal.student_ids and sid in proposal.student_ids:
            proposal.student_ids = [i for i in proposal.student_ids if i != sid]
    for login in db.query(User).filter(User.student_id == sid):
        login.student_id = None
        login.full_name = "Removed student"
        login.email = f"removed-student-{login.id}@removed.invalid"
        login.hashed_password = UNUSABLE_PASSWORD
        login.is_active = False
        login.token_version += 1
    db.query(AuditLogEntry).filter(
        AuditLogEntry.entity_type.in_(("student", "student_home")),
        AuditLogEntry.entity_id == sid,
    ).update({"before_state": None, "after_state": None}, synchronize_session=False)
    withdrawn = student.withdrawn_on
    db.flush()
    db.delete(student)
    record_audit(
        db,
        entity_type="student",
        entity_id=sid,
        action="deleted_after_retention",
        actor=None,
        after_state={"withdrawn_on": withdrawn.isoformat() if withdrawn else None},
    )


def run(db: Session, now: datetime | None = None) -> int:
    """For the worker: deletes every withdrawn student whose time is up."""
    today = district_now(load_rules(db), now or utc_now()).date()
    due = [
        s
        for s in db.query(Student).filter(Student.withdrawn_on.is_not(None)).all()
        if s.withdrawn_on is not None and delete_after(s.withdrawn_on) < today
    ]
    for student in due:
        purge(db, student)
        db.commit()
    return len(due)
