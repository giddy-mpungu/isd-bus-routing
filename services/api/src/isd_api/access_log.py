"""Who at the district looked at a student's information (FERPA, Phase 5).

Decided by the product owner on 2026-10-07: every staff view of a student
is recorded, so the district can answer "who has seen my child's record"
and spot misuse. A view is one `StudentAccess` row per person, student,
kind of view and day (the first time that day), which keeps the log
small however often a page is reloaded. Parents and students looking at
their own family aren't staff views and aren't logged here (a records
download is in the audit trail instead).

Kinds (`WHAT`): the student list, a home address, guardians, a run's
expected riders, a driver's roster, stop proposals, a records download.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from isd_api.models import Role, StudentAccess, User

WHAT = {
    "list": "the student list",
    "home": "the home address",
    "guardians": "the guardians",
    "riders": "a run's expected riders",
    "roster": "a driver's roster",
    "stop_proposals": "stop proposals",
    "records": "a download of the records",
}

_NOT_STAFF = {Role.PARENT, Role.STUDENT}


def record_views(db: Session, user: User, student_ids: Iterable[int], what: str) -> None:
    """Notes that `user` saw these students' `what` today. Commits; never
    fails the request it is part of."""
    if user.role in _NOT_STAFF:
        return
    assert what in WHAT, what
    ids = set(student_ids)
    if not ids:
        return
    now = datetime.now(UTC)
    today = now.date()
    already = {
        row.student_id
        for row in db.query(StudentAccess.student_id).filter(
            StudentAccess.user_id == user.id,
            StudentAccess.what == what,
            StudentAccess.day == today,
            StudentAccess.student_id.in_(ids),
        )
    }
    missing = ids - already
    if not missing:
        return
    db.add_all(
        StudentAccess(student_id=sid, user_id=user.id, what=what, day=today, first_at=now)
        for sid in missing
    )
    try:
        db.commit()
    except IntegrityError:
        # The same view recorded by a parallel request a moment ago.
        db.rollback()
