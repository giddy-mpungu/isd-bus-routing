"""The scheduled SIS roster sync (spec section 19).

Decisions by the product owner (2026-10-06): pull from the district's
OneRoster REST API (integrations/oneroster_api.py) every night at
`ISD_API_SIS_SYNC_TIME` (03:00 district time, after the 02:00 backup, so
a bad sync can be rolled back), plus "Sync now" on the Setup page. Safe
changes are applied without waiting: new students, and name, school and
grade changes of students already linked by SIS ID. Everything that needs
a person waits on the Setup page: a possible duplicate of a hand-entered
student (never linked by name automatically), an unmapped or ambiguous
school, a removal request (never applied). Transportation admins are
emailed only when a sync fails or leaves something waiting.

The same reconciliation rules as the CSV upload (isd_api/sis_reconcile.py).
Every run is kept as a `SisSyncRun`; a scheduled one is unique per day, so
a restart or a second worker never syncs twice.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from isd_api import mailer
from isd_api.config import settings
from isd_api.integrations import oneroster_api
from isd_api.integrations.oneroster import OneRosterFormatError, parse_students_api
from isd_api.mailer import Email
from isd_api.models import Role, SisSyncRun, User
from isd_api.ridership_rules import district_now, load_rules, utc_now
from isd_api.sis_reconcile import reconcile

logger = logging.getLogger(__name__)

ATTENTION = ("needs_review", "removal_requested", "error")
MAX_KEPT_PROBLEMS = 200
# A run still marked running after this long was interrupted (a restart).
STALE_AFTER = timedelta(minutes=15)


class SyncAlreadyRunning(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _close_stale_runs(db: Session) -> None:
    cutoff = _now() - STALE_AFTER
    for stale in db.query(SisSyncRun).filter(SisSyncRun.status == "running").all():
        started = (
            stale.started_at if stale.started_at.tzinfo else stale.started_at.replace(tzinfo=UTC)
        )
        if started < cutoff:
            stale.status = "failed"
            stale.error = "Interrupted before it finished"
            stale.finished_at = _now()
    db.commit()


def run_sync(
    db: Session, *, trigger: str, actor: User | None, scheduled_for: date | None = None
) -> SisSyncRun:
    """One sync, start to finish; returns its record."""
    _close_stale_runs(db)
    if trigger == "manual" and db.query(SisSyncRun).filter_by(status="running").first():
        raise SyncAlreadyRunning("A sync is already running")
    run = SisSyncRun(
        trigger=trigger,
        status="running",
        started_at=_now(),
        scheduled_for=scheduled_for,
        triggered_by_user_id=actor.id if actor else None,
    )
    db.add(run)
    db.commit()  # a second scheduled run for the same day stops here (unique)
    run_id = run.id

    try:
        parsed = parse_students_api(oneroster_api.fetch_students())
        result = reconcile(
            db, parsed, dry_run=False, link_by_name=False, actor=actor, audit_prefix="sis_sync"
        )
        run = db.get(SisSyncRun, run_id) or run
        run.counts = result.counts
        run.problems = [r.model_dump() for r in result.rows if r.action in ATTENTION][
            :MAX_KEPT_PROBLEMS
        ]
        run.status = "needs_attention" if any(result.counts[a] for a in ATTENTION) else "ok"
    except (oneroster_api.OneRosterApiError, OneRosterFormatError) as exc:
        db.rollback()
        run = db.get(SisSyncRun, run_id) or run
        run.status = "failed"
        run.error = str(exc)[:500]
    except Exception:
        logger.exception("SIS sync failed unexpectedly")
        db.rollback()
        run = db.get(SisSyncRun, run_id) or run
        run.status = "failed"
        run.error = "Something went wrong during the sync; the api log has the details"
    run.finished_at = _now()
    db.commit()
    if run.status != "ok":
        _tell_admins(db, run)
    return run


def run_if_due(db: Session, now: datetime | None = None) -> int:
    """For the worker: the nightly sync, once per district day."""
    if not oneroster_api.is_configured():
        return 0
    local = district_now(load_rules(db), now or utc_now())
    hours, minutes = settings.sis_sync_time.split(":")
    if local.hour * 60 + local.minute < int(hours) * 60 + int(minutes):
        return 0
    today = local.date()
    if db.query(SisSyncRun).filter_by(scheduled_for=today).first() is not None:
        return 0
    try:
        run_sync(db, trigger="scheduled", actor=None, scheduled_for=today)
    except IntegrityError:
        db.rollback()  # another worker started today's sync first
        return 0
    return 1


def _tell_admins(db: Session, run: SisSyncRun) -> None:
    """Counts only, no student names: the details wait on the Setup page."""
    if not mailer.is_configured():
        return
    admins = (
        db.query(User)
        .filter(User.role == Role.TRANSPORTATION_ADMIN, User.is_active.is_(True))
        .all()
    )
    if run.status == "failed":
        subject = "The SIS roster sync failed"
        what = f"The {run.trigger} roster sync failed: {run.error}"
    else:
        counts = run.counts or {}
        waiting = ", ".join(
            f"{counts.get(a, 0)} {label}"
            for a, label in (
                ("needs_review", "to review"),
                ("removal_requested", "removal requests"),
                ("error", "rows with problems"),
            )
            if counts.get(a)
        )
        subject = "The SIS roster sync needs a look"
        what = (
            f"The {run.trigger} roster sync applied {counts.get('created', 0)} new and "
            f"{counts.get('updated', 0)} changed students, and left {waiting} for you."
        )
    for admin in admins:
        mailer.send_quietly(
            Email(
                to=admin.email,
                subject=subject,
                body=(
                    f"Hello {admin.full_name},\n\n{what}\n\n"
                    "See the details under Setup, SIS import: "
                    f"{settings.web_url}/setup?tab=sis-import\n\n"
                    "isd-bus-routing, your district's school transportation system\n"
                ),
            )
        )
