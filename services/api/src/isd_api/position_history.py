"""GPS position history (spec sections 9 "route progress" and 20).

`VehiclePosition` keeps only each crew's latest position, for the live
fleet view (ADR 0009). Every report is also appended here as a
`PositionSample`, for a bus's track on the map and the positions report.

Retention: samples older than `settings.position_history_days` are
deleted. A track shows where a bus full of students was, so it isn't
kept longer than operations need. Pruning runs on the write path at most
once an hour per process, so there's no separate job to schedule.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from isd_api.config import settings
from isd_api.models import Crew, PositionSample

PRUNE_INTERVAL_SECONDS = 3600
_last_prune: float | None = None


def _monotonic() -> float:
    # Its own function so tests can move this clock without touching
    # time.monotonic for everything else in the process.
    return time.monotonic()


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def record_sample(db: Session, crew: Crew, lat: float, lon: float, recorded_at: datetime) -> None:
    """Appends one report. A repeat of the same reading (a tablet retrying
    after a dropped connection) is stored once."""
    recorded_at = _as_utc(recorded_at)
    exists = (
        db.query(PositionSample.id)
        .filter(PositionSample.crew_id == crew.id, PositionSample.recorded_at == recorded_at)
        .first()
    )
    if exists is None:
        db.add(
            PositionSample(
                crew_id=crew.id, location_lat=lat, location_lon=lon, recorded_at=recorded_at
            )
        )
    maybe_prune(db)


def prune(db: Session, now: datetime | None = None) -> int:
    """Deletes samples past the retention period; returns how many."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.position_history_days)
    return (
        db.query(PositionSample)
        .filter(PositionSample.recorded_at < cutoff)
        .delete(synchronize_session=False)
    )


def maybe_prune(db: Session) -> None:
    global _last_prune
    now = _monotonic()
    if _last_prune is None or now - _last_prune >= PRUNE_INTERVAL_SECONDS:
        _last_prune = now
        prune(db)


def track(db: Session, crew_id: int) -> list[PositionSample]:
    return (
        db.query(PositionSample)
        .filter(PositionSample.crew_id == crew_id)
        .order_by(PositionSample.recorded_at)
        .all()
    )
