"""Transportation eligibility and grade-band limits (spec sections 3, 3.1).

A student is bus-eligible when any of these holds:
  - they receive specialized transportation,
  - an admin marked their walk to school hazardous,
  - their home is at least `eligibility_miles` from their school.
Otherwise, or with no home location on file, they're not (the reason
says which).

Distance is straight-line for now. A road-distance check comes with the
routing work (Phase 3.4); straight-line never overstates the distance, so
it can only err towards "not eligible", which an admin can override with
the hazardous-route flag.

Grade bands (spec section 3.1 "walking-distance limits may differ for"):
Pre-K, elementary (K-5), middle (6-8), high (9-12), and specialized
transportation, which takes precedence. The district's defaults, agreed
with the product owner on 2026-09-28: elementary and Pre-K walk up to a
quarter mile and ride up to 45 minutes; middle and high walk up to half a
mile and ride up to an hour; bus-eligible at 2 miles (the Texas rule).
Specialized transportation defaults to curb-to-curb (0 miles) and an hour.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from isd_api.models import Student, StudentHome, TransportationRules

GRADES = ["PK", "K", *[str(n) for n in range(1, 13)]]

PREK, ELEMENTARY, MIDDLE, HIGH, SPECIALIZED = (
    "prek",
    "elementary",
    "middle",
    "high",
    "specialized",
)
BANDS = [PREK, ELEMENTARY, MIDDLE, HIGH, SPECIALIZED]
BAND_LABELS = {
    PREK: "Pre-K",
    ELEMENTARY: "Elementary (K-5)",
    MIDDLE: "Middle (6-8)",
    HIGH: "High (9-12)",
    SPECIALIZED: "Specialized transportation",
}

DEFAULTS = {
    "eligibility_miles": 2.0,
    "walk_miles_prek": 0.25,
    "walk_miles_elementary": 0.25,
    "walk_miles_middle": 0.5,
    "walk_miles_high": 0.5,
    "walk_miles_specialized": 0.0,
    "ride_minutes_prek": 45,
    "ride_minutes_elementary": 45,
    "ride_minutes_middle": 60,
    "ride_minutes_high": 60,
    "ride_minutes_specialized": 60,
    "min_stop_spacing_miles": 0.1,
}
_RULES_ID = 1

METRES_PER_MILE = 1609.344
_EARTH_RADIUS_M = 6_371_000


@dataclass(frozen=True)
class Rules:
    eligibility_miles: float
    walk_miles: dict[str, float]
    ride_minutes: dict[str, int]
    min_stop_spacing_miles: float
    is_default: bool


def load_rules(db: Session) -> Rules:
    row = db.get(TransportationRules, _RULES_ID)
    values = DEFAULTS if row is None else {key: getattr(row, key) for key in DEFAULTS}
    return Rules(
        eligibility_miles=float(values["eligibility_miles"]),
        walk_miles={band: float(values[f"walk_miles_{band}"]) for band in BANDS},
        ride_minutes={band: int(values[f"ride_minutes_{band}"]) for band in BANDS},
        min_stop_spacing_miles=float(values["min_stop_spacing_miles"]),
        is_default=row is None,
    )


def normalize_grade(value: str | None) -> str | None:
    """ "PK"/"K"/"1".."12" from common spellings: OneRoster/CEDS codes
    (PK, TK, PR, IT, PS, KG, 01..12), "k", "3rd". Anything else is None."""
    if value is None:
        return None
    text = value.strip().upper()
    if text in {"PK", "TK", "PR", "IT", "PS", "PRE-K", "PREK"}:
        return "PK"
    if text in {"K", "KG", "KINDERGARTEN"}:
        return "K"
    for suffix in ("ST", "ND", "RD", "TH"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    if text.isdigit() and 1 <= int(text) <= 12:
        return str(int(text))
    return None


def band_for(student: Student) -> str | None:
    """The student's limits band, or None when the grade isn't known."""
    if student.needs_specialized_transport:
        return SPECIALIZED
    if student.grade is None:
        return None
    if student.grade == "PK":
        return PREK
    if student.grade == "K" or int(student.grade) <= 5:
        return ELEMENTARY
    if int(student.grade) <= 8:
        return MIDDLE
    return HIGH


def miles_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h)) / METRES_PER_MILE


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason: str
    # Straight-line miles from home to school, to two decimals, when known.
    miles_from_school: float | None
    band: str | None


def eligibility_for(student: Student, home: StudentHome | None, rules: Rules) -> Eligibility:
    band = band_for(student)
    exact = (
        None
        if home is None
        else miles_between(
            home.location_lat,
            home.location_lon,
            student.school.location_lat,
            student.school.location_lon,
        )
    )
    # Shown to two decimals, rounded down, so it never reads as over the
    # limit when it isn't; compared unrounded.
    miles = None if exact is None else math.floor(exact * 100) / 100
    if student.needs_specialized_transport:
        return Eligibility(True, "Specialized transportation", miles, band)
    if student.hazardous_route:
        return Eligibility(True, "Hazardous walking route", miles, band)
    if exact is None or miles is None:
        return Eligibility(False, "No home location on file", None, band)
    limit = rules.eligibility_miles
    if exact >= limit:
        return Eligibility(True, f"{miles:.2f} mi from school (at least {limit:g} mi)", miles, band)
    return Eligibility(False, f"{miles:.2f} mi from school (under {limit:g} mi)", miles, band)
