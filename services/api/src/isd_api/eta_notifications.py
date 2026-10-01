"""Emailing families when their child's bus time changes (Phase 5.5).

Decisions by the product owner (2026-10-01): on by default for parents,
with a switch on the Family page and a link in every email to turn it
off; an email when today's estimate for a child's pickup or drop-off is
`ISD_API_ETA_EMAIL_THRESHOLD_MINUTES` (10) or more from the plan, and
again only when it moves that much from what was last sent (so "back on
time" is sent too); only on the service day, from
`ISD_API_ETA_EMAIL_EARLIEST` (05:30 district time), and never once that
pickup or drop-off time has passed.

`run` is called every couple of minutes by the worker (isd_api/worker.py).
Estimates are the same ones the Family page shows (isd_api/daily_trip.py).
Each send is recorded first (`EtaNotification`, unique per child,
parent, day, leg and time), so a restart or a second worker never sends
the same email twice; a failed send removes its record, to be retried.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

import jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from isd_api import mailer
from isd_api.config import settings
from isd_api.daily_trip import TripStop, daily_trip
from isd_api.mailer import Email
from isd_api.models import EtaNotification, RideDirection, Role, Run, Student, User
from isd_api.ridership_rules import district_now, hhmm, load_rules, utc_now

logger = logging.getLogger(__name__)

OPT_OUT_PURPOSE = "eta-optout"
OPT_OUT_DAYS = 90
LEG = {RideDirection.AM: "morning pickup", RideDirection.PM: "afternoon drop-off"}


def opt_out_token(user: User) -> str:
    return jwt.encode(
        {
            "purpose": OPT_OUT_PURPOSE,
            "sub": str(user.id),
            "exp": datetime.now(UTC) + timedelta(days=OPT_OUT_DAYS),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def user_for_opt_out(db: Session, token: str) -> User | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("purpose") != OPT_OUT_PURPOSE:
        return None
    return db.get(User, int(payload["sub"]))


def change_email(parent: User, student: Student, direction: RideDirection, stop: TripStop) -> Email:
    assert stop.eta_minute is not None
    planned = f" (planned {hhmm(stop.planned_minute)})" if stop.planned_minute is not None else ""
    link = f"{settings.web_url}/email-preferences#token={opt_out_token(parent)}"
    return Email(
        to=parent.email,
        subject=f"Bus time change for {student.full_name}: {hhmm(stop.eta_minute)}",
        body=(
            f"Hello {parent.full_name},\n\n"
            f"Today's {LEG[direction]} for {student.full_name} at {stop.label} is now "
            f"expected at about {hhmm(stop.eta_minute)}{planned}.\n\n"
            "Times are estimates and can move again; the Family page always shows the "
            f"latest: {settings.web_url}/family\n\n"
            f"To stop these emails: {link}\n\n"
            "isd-bus-routing, your district's school transportation system\n"
        ),
    )


def _last_sent(
    db: Session, student_id: int, user_id: int, service_date: date, direction: RideDirection
) -> int | None:
    row = (
        db.query(EtaNotification)
        .filter_by(
            student_id=student_id, user_id=user_id, service_date=service_date, direction=direction
        )
        .order_by(EtaNotification.sent_at.desc(), EtaNotification.id.desc())
        .first()
    )
    return row.eta_minute if row else None


def _earliest_minute() -> int:
    hours, minutes = settings.eta_email_earliest.split(":")
    return int(hours) * 60 + int(minutes)


def run(db: Session, now: datetime | None = None) -> int:
    """One pass: sends what's due and returns how many emails went out."""
    if not mailer.is_configured():
        return 0
    local = district_now(load_rules(db), now or utc_now())
    now_minute = local.hour * 60 + local.minute
    if now_minute < _earliest_minute():
        return 0
    service_date = local.date()
    threshold = settings.eta_email_threshold_minutes
    sent = 0

    runs = db.query(Run).filter(Run.service_date == service_date).order_by(Run.id).all()
    for run_ in runs:
        if run_.assignment is None:
            continue
        for stop in daily_trip(db, run_, run_.assignment.start_minute) or []:
            if stop.skipped or stop.eta_minute is None or stop.eta_minute <= now_minute:
                continue
            for student in stop.riders:
                for parent in student.guardians:
                    if (
                        parent.role != Role.PARENT
                        or not parent.is_active
                        or not parent.eta_emails_enabled
                    ):
                        continue
                    baseline = _last_sent(db, student.id, parent.id, service_date, run_.direction)
                    if baseline is None:
                        baseline = stop.planned_minute
                    if baseline is None or abs(stop.eta_minute - baseline) < threshold:
                        continue
                    record = EtaNotification(
                        student_id=student.id,
                        user_id=parent.id,
                        service_date=service_date,
                        direction=run_.direction,
                        eta_minute=stop.eta_minute,
                        sent_at=datetime.now(UTC),
                    )
                    db.add(record)
                    try:
                        db.commit()
                    except IntegrityError:
                        db.rollback()  # another worker got there first
                        continue
                    try:
                        mailer.send(change_email(parent, student, run_.direction, stop))
                        sent += 1
                    except Exception:
                        logger.exception("Couldn't send a bus time email; will retry")
                        db.delete(record)
                        db.commit()
    return sent
