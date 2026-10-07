"""Families asking for a student's record to be corrected (FERPA's right to
request amendment).

Decided by the product owner on 2026-10-07: a form per child on the Family
page, and a queue for transportation admins (Setup, Corrections), who
accept (and make the fix) or decline with a reason; the family sees the
outcome and is emailed. A declined request tells the family they may ask
the district for a hearing, as FERPA provides. Emails carry no student
details beyond the child's first name to the family; admins get a link.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api import mailer
from isd_api.audit import record as record_audit
from isd_api.config import settings
from isd_api.db import get_db
from isd_api.mailer import Email
from isd_api.models import RecordCorrection, Role, Student, User
from isd_api.routers.students import _linked_students
from isd_api.schemas import CorrectionCreate, CorrectionDecision, CorrectionRead
from isd_api.security import require_role

router = APIRouter(tags=["corrections"])

MAX_OPEN_PER_PERSON = 10
HEARING = (
    "If you disagree, you can ask the district for a hearing about this decision, and "
    "add a statement to the record explaining why."
)
SIGNATURE = "\n\nisd-bus-routing, your district's school transportation system\n"


def _read(db: Session, c: RecordCorrection) -> CorrectionRead:
    student = db.get(Student, c.student_id)
    requester = db.get(User, c.requested_by_user_id)
    return CorrectionRead(
        id=c.id,
        student_id=c.student_id,
        student_name=student.full_name if student else "",
        requested_by=requester.full_name if requester else "",
        created_at=c.created_at,
        what_is_wrong=c.what_is_wrong,
        should_say=c.should_say,
        status=c.status,
        decided_at=c.decided_at,
        response=c.response,
    )


def _family_student(db: Session, user: User, student_id: int) -> Student:
    student = next((s for s in _linked_students(db, user) if s.id == student_id), None)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return student


@router.post(
    "/students/{student_id}/corrections",
    response_model=CorrectionRead,
    status_code=status.HTTP_201_CREATED,
)
def request_correction(
    student_id: int,
    payload: CorrectionCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.PARENT, Role.STUDENT)),
) -> CorrectionRead:
    _family_student(db, current_user, student_id)
    open_count = (
        db.query(RecordCorrection)
        .filter_by(requested_by_user_id=current_user.id, status="open")
        .count()
    )
    if open_count >= MAX_OPEN_PER_PERSON:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have several requests waiting already; the office will answer those first.",
        )
    correction = RecordCorrection(
        student_id=student_id,
        requested_by_user_id=current_user.id,
        created_at=datetime.now(UTC),
        what_is_wrong=payload.what_is_wrong.strip(),
        should_say=payload.should_say.strip(),
        status="open",
    )
    db.add(correction)
    db.flush()
    record_audit(
        db,
        entity_type="student",
        entity_id=student_id,
        action="correction_requested",
        actor=current_user,
        after_state={"correction_id": correction.id},
    )
    db.commit()
    if mailer.is_configured():
        admins = db.query(User).filter(
            User.role == Role.TRANSPORTATION_ADMIN, User.is_active.is_(True)
        )
        for admin in admins:
            background.add_task(
                mailer.send_quietly,
                Email(
                    to=admin.email,
                    subject="A family asked for a record correction",
                    body=(
                        f"Hello {admin.full_name},\n\nA family asked for a correction to a "
                        "student's transportation record. Please answer it under Setup, "
                        f"Corrections: {settings.web_url}/setup?tab=corrections" + SIGNATURE
                    ),
                ),
            )
    return _read(db, correction)


@router.get("/students/{student_id}/corrections", response_model=list[CorrectionRead])
def list_student_corrections(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(Role.PARENT, Role.STUDENT, Role.TRANSPORTATION_ADMIN)
    ),
) -> list[CorrectionRead]:
    if current_user.role != Role.TRANSPORTATION_ADMIN:
        _family_student(db, current_user, student_id)
    rows = (
        db.query(RecordCorrection)
        .filter_by(student_id=student_id)
        .order_by(RecordCorrection.id.desc())
        .all()
    )
    return [_read(db, c) for c in rows]


@router.get("/corrections", response_model=list[CorrectionRead])
def list_corrections(
    status_filter: str = "open",
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> list[CorrectionRead]:
    """The admin queue: open requests oldest first, or every request newest first."""
    query = db.query(RecordCorrection)
    if status_filter == "open":
        query = query.filter_by(status="open").order_by(RecordCorrection.id)
    else:
        query = query.order_by(RecordCorrection.id.desc())
    return [_read(db, c) for c in query.limit(500).all()]


@router.patch("/corrections/{correction_id}", response_model=CorrectionRead)
def decide_correction(
    correction_id: int,
    payload: CorrectionDecision,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> CorrectionRead:
    """Accept (the admin makes the fix in the record) or decline, with a
    reason the family sees."""
    correction = db.get(RecordCorrection, correction_id)
    if correction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if correction.status != "open":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already answered")
    correction.status = payload.decision
    correction.response = payload.response.strip()
    correction.decided_by_user_id = current_user.id
    correction.decided_at = datetime.now(UTC)
    record_audit(
        db,
        entity_type="student",
        entity_id=correction.student_id,
        action=f"correction_{payload.decision}",
        actor=current_user,
        after_state={"correction_id": correction.id},
    )
    db.commit()
    requester = db.get(User, correction.requested_by_user_id)
    student = db.get(Student, correction.student_id)
    if mailer.is_configured() and requester is not None and requester.is_active:
        first = student.full_name.split(" ")[0] if student else "your child"
        outcome = (
            "accepted, and the record has been corrected"
            if payload.decision == "accepted"
            else "declined"
        )
        extra = f"\n\n{HEARING}" if payload.decision == "declined" else ""
        background.add_task(
            mailer.send_quietly,
            Email(
                to=requester.email,
                subject="Your record correction request was answered",
                body=(
                    f"Hello {requester.full_name},\n\nYour request to correct {first}'s "
                    f"transportation record was {outcome}.\n\nThe office wrote: "
                    f"{correction.response}{extra}\n\nSee it on the Family page: "
                    f"{settings.web_url}/family" + SIGNATURE
                ),
            ),
        )
    return _read(db, correction)
