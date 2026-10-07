"""Ridership reporting rules (spec sections 4.4 and 4.5).

The district sets its time zone and optional AM/PM cutoff times. Families
can't change a past day's ridership, or today's after that leg's cutoff.
Staff can still record a late change (human override, spec section 21),
for example a phone-in. A request to ride is refused for everyone when the
bus serving that leg is already at capacity (spec section 15).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from isd_api.models import RideDirection, RidershipRules

DEFAULT_TIMEZONE = "America/Chicago"
_RULES_ID = 1


@dataclass(frozen=True)
class Rules:
    timezone: str
    am_cutoff_minute: int | None
    pm_cutoff_minute: int | None
    is_default: bool

    def cutoff_for(self, direction: RideDirection) -> int | None:
        return self.am_cutoff_minute if direction == RideDirection.AM else self.pm_cutoff_minute


def load_rules(db: Session) -> Rules:
    row = db.get(RidershipRules, _RULES_ID)
    if row is None:
        return Rules(DEFAULT_TIMEZONE, None, None, is_default=True)
    return Rules(row.timezone, row.am_cutoff_minute, row.pm_cutoff_minute, is_default=False)


def utc_now() -> datetime:
    """The one clock read here, so tests can pin it."""
    return datetime.now(UTC)


def district_now(rules: Rules, now: datetime | None = None) -> datetime:
    """The current wall-clock time in the district's own time zone."""
    return (now or utc_now()).astimezone(ZoneInfo(rules.timezone))


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


PAST_DAY = "Ridership for a past day can't be changed."
CLOSED_TODAY = (
    "Changes to today's {leg} ride closed at {time}. Please contact the transportation office."
)


def change_closed_reason(
    rules: Rules, service_date: date, direction: RideDirection, now: datetime | None = None
) -> str | None:
    """Why a family can no longer change this leg, or None if they can."""
    local = district_now(rules, now)
    today = local.date()
    if service_date < today:
        return PAST_DAY
    cutoff = rules.cutoff_for(direction)
    if service_date == today and cutoff is not None and local.hour * 60 + local.minute >= cutoff:
        return CLOSED_TODAY.format(leg=direction.value.upper(), time=hhmm(cutoff))
    return None
