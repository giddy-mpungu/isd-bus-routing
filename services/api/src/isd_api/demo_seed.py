"""A fictional demo district, for local demos and beta testing only.

Everything here is invented — the district, schools, students, and
people. Never load real student data into a demo install: a demo is
often shared over a public tunnel (see docs/demo.md) with far weaker
operational safeguards than a real deployment.

The seed goes through the real HTTP API (validation, RBAC, audit log,
and the solver all run exactly as they would for a person clicking
through the UI) rather than writing rows directly. The one exception is
the very first transportation_admin, created the same way
scripts/bootstrap_admin.py does, since POST /users needs an admin to
already exist.

`request` is any callable ``(method, path, json_body) -> parsed JSON``
that raises on a non-2xx response, so the same seed runs against the
real server (scripts/seed_demo.py, over urllib) and in tests (over
FastAPI's TestClient).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from isd_api.models import Role, User
from isd_api.security import hash_password

Request = Callable[[str, str, dict[str, Any] | None], Any]

DEMO_EMAIL_DOMAIN = "demo.example.org"
ADMIN_EMAIL = f"admin@{DEMO_EMAIL_DOMAIN}"
ADMIN_NAME = "Avery Admin (demo)"

# How many days of schedule to generate, starting from `start_date`.
# Templates run every day of the week (not just Mon-Fri) so a demo
# opened on a weekend still has something on today's schedule.
DEFAULT_DAYS = 14
ALL_WEEK = [0, 1, 2, 3, 4, 5, 6]


class AlreadySeededError(RuntimeError):
    """Raised when the database already has users — the seed only ever
    runs against an empty install, so it can't clobber real data."""


@dataclass(frozen=True)
class DemoAccount:
    role: str
    email: str
    password: str
    full_name: str
    note: str


def generate_password() -> str:
    # 12 URL-safe characters (~72 bits): a demo is often reachable from
    # the internet, so no guessable shared password.
    return secrets.token_urlsafe(9)


def create_demo_admin(db: Session, password: str) -> DemoAccount:
    if db.query(User).count() > 0:
        raise AlreadySeededError(
            "Users already exist in this database; the demo seed only runs on an empty install."
        )
    db.add(
        User(
            email=ADMIN_EMAIL,
            hashed_password=hash_password(password),
            full_name=ADMIN_NAME,
            role=Role.TRANSPORTATION_ADMIN,
        )
    )
    db.commit()
    return DemoAccount(
        role="transportation_admin",
        email=ADMIN_EMAIL,
        password=password,
        full_name=ADMIN_NAME,
        note="Full access: Setup, Users, Templates, Schedule, Field Trips.",
    )


# --- Fictional master data --------------------------------------------------

# Three schools a few km apart whose bell windows overlap, so every
# standing crew is needed each morning and afternoon. With staggered
# bells the solver's crew-minimizing objective chains all six runs onto
# one bus, leaving the other demo drivers' apps empty.
_SCHOOLS = [
    # name, lat, lon, (AM earliest, latest, duration), (PM ...), required quals
    ("Maple Valley High School", 29.7610, -95.3700, (390, 440, 40), (870, 920, 40), []),
    ("Cedar Ridge Middle School", 29.7480, -95.3890, (395, 445, 35), (875, 925, 35), []),
    ("Willow Creek Elementary", 29.7705, -95.3995, (400, 455, 35), (880, 935, 35), ["lift"]),
]

_STOPS = [
    ("Oak St & 3rd Ave", 29.7555, -95.3805),
    ("Birch Ln Cul-de-sac", 29.7650, -95.3920),
    ("Pinecrest Apartments", 29.7520, -95.3985),
    ("Riverside Park Entrance", 29.7690, -95.3780),
    ("Elm St & Maple Dr", 29.7445, -95.3760),
    ("Hillcrest Community Center", 29.7735, -95.3870),
]

# name, school index, stop index, rides by default
_STUDENTS = [
    ("Mia Alvarez", 0, 0, True),
    ("Noah Bennett", 0, 3, True),
    ("Liam Chen", 0, 4, False),
    ("Ava Dubois", 1, 1, True),
    ("Ethan Foster", 1, 4, True),
    ("Zoe Garcia", 1, 2, True),
    ("Lucas Hughes", 1, 5, False),
    ("Emma Ibrahim", 2, 0, True),
    ("Oliver Jensen", 2, 1, True),
    ("Sofia Kowalski", 2, 2, True),
    ("Leo Martins", 2, 3, True),
    ("Chloe Nakamura", 2, 5, True),
]

_DRIVERS = [
    ("Jordan Rivera", ["CDL_B"]),
    ("Sam Okafor", ["CDL_B"]),
    ("Taylor Brooks", ["CDL_B"]),
    # No crew template: the substitute pool for the absences workflow.
    ("Casey Morgan", ["CDL_B"]),
]

# label, nominal, effective, length, width, height, weight, quals
_VEHICLES = [
    ("Bus 07", 72, 66, 12.2, 2.5, 3.2, 14500.0, []),
    ("Bus 12 (lift)", 48, 40, 10.7, 2.5, 3.3, 13200.0, ["lift"]),
    ("Bus 19", 72, 66, 12.2, 2.5, 3.2, 14500.0, []),
    ("Van 03", 14, 12, 6.1, 2.1, 2.6, 4200.0, []),
]


def seed_demo(
    request: Request,
    *,
    start_date: date,
    days: int = DEFAULT_DAYS,
    password_factory: Callable[[], str] = generate_password,
) -> list[DemoAccount]:
    """Create the demo district through the API as an already-logged-in
    transportation_admin. Returns every login it created, for the
    caller to hand to the demo's testers."""

    def post(path: str, body: dict[str, Any] | None = None) -> Any:
        return request("POST", path, body)

    accounts: list[DemoAccount] = []

    def add_user(role: str, local_part: str, full_name: str, note: str, **links: int) -> Any:
        password = password_factory()
        email = f"{local_part}@{DEMO_EMAIL_DOMAIN}"
        user = post(
            "/users",
            {"email": email, "password": password, "full_name": full_name, "role": role, **links},
        )
        accounts.append(DemoAccount(role, email, password, full_name, note))
        return user

    # Qualifications
    post("/qualifications", {"code": "CDL_B", "kind": "license", "description": "Class B CDL"})
    post(
        "/qualifications",
        {"code": "lift", "kind": "vehicle_capability", "description": "Wheelchair lift"},
    )

    # Schools, stops, students
    schools = [
        post("/schools", {"name": name, "location_lat": lat, "location_lon": lon})
        for name, lat, lon, *_ in _SCHOOLS
    ]
    stops = [
        post("/stops", {"label": label, "location_lat": lat, "location_lon": lon})
        for label, lat, lon in _STOPS
    ]
    students = [
        post(
            "/students",
            {
                "full_name": name,
                "school_id": schools[school_i]["id"],
                "stop_id": stops[stop_i]["id"],
                "default_ridership": "rides" if rides else "does_not_ride",
            },
        )
        for name, school_i, stop_i, rides in _STUDENTS
    ]

    # Fleet
    drivers = [
        post("/drivers", {"full_name": name, "qualification_codes": quals})
        for name, quals in _DRIVERS
    ]
    vehicles = [
        post(
            "/vehicles",
            {
                "label": label,
                "nominal_capacity": nominal,
                "effective_capacity": effective,
                "length_m": length,
                "width_m": width,
                "height_m": height,
                "weight_kg": weight,
                "qualification_codes": quals,
            },
        )
        for label, nominal, effective, length, width, height, weight, quals in _VEHICLES
    ]

    # Recurring templates (spec section 11): one AM and one PM run per
    # school, and three standing driver+vehicle crews. The lift-equipped
    # bus is in a crew, so the elementary runs that need it are feasible.
    for school, (_, _, _, am, pm, quals) in zip(schools, _SCHOOLS, strict=True):
        for direction, (earliest, latest, duration) in (("am", am), ("pm", pm)):
            post(
                "/route-templates",
                {
                    "school_id": school["id"],
                    "direction": direction,
                    "window_earliest": earliest,
                    "window_latest": latest,
                    "duration_minutes": duration,
                    "buffer_minutes": 5,
                    "days_of_week": ALL_WEEK,
                    "required_qualification_codes": quals,
                },
            )
    for driver, vehicle in zip(drivers[:3], vehicles[:3], strict=True):
        post(
            "/crew-templates",
            {
                "driver_id": driver["id"],
                "vehicle_id": vehicle["id"],
                "available_window_earliest": 360,
                "available_window_latest": 1020,
                "days_of_week": ALL_WEEK,
            },
        )

    # Generate and solve each day, exactly as a dispatcher would.
    for offset in range(days):
        service_date = (start_date + timedelta(days=offset)).isoformat()
        post(f"/schedule/{service_date}/generate-from-templates")
        post("/schedule", {"service_date": service_date})

    # District knowledge (spec section 8) and announcements (section 9/18)
    post(
        "/geographic-knowledge",
        {
            "location_lat": 29.7530,
            "location_lon": -95.3840,
            "category": "frequent_flooding",
            "note": "Low-water crossing on Bayou Rd floods after heavy rain; routing avoids it.",
        },
    )
    post(
        "/geographic-knowledge",
        {
            "location_lat": 29.7700,
            "location_lon": -95.3990,
            "category": "preferred_entrance",
            "note": "Use the north bus loop, not the front office drive.",
            "school_id": schools[2]["id"],
        },
    )
    post(
        "/announcements",
        {
            "message": "Welcome to the Maple Valley ISD transportation demo!",
            "category": "general",
            "audience": "all",
        },
    )
    post(
        "/announcements",
        {
            "message": "Willow Creek dismissal moves 15 minutes earlier this Friday.",
            "category": "route_change",
            "audience": "family",
            "school_id": schools[2]["id"],
        },
    )

    # An upcoming field trip (spec section 12), unassigned so a tester
    # can try the candidate/conflict check and assignment flow.
    trip_day = start_date + timedelta(days=2)
    post(
        "/field-trips",
        {
            "requesting_party": "Cedar Ridge Middle School — 7th grade science",
            "origin": "Cedar Ridge Middle School",
            "destination": "Gulf Coast Science Museum",
            "departure_at": datetime.combine(trip_day, time(9, 0)).isoformat(),
            "expected_return_at": datetime.combine(trip_day, time(13, 30)).isoformat(),
            "passenger_count": 38,
            "trip_contact": "Ms. Patel, 555-0142",
        },
    )

    # One login per role, each linked to the record it acts for.
    add_user(
        "dispatcher",
        "dispatcher",
        "Dana Dispatcher (demo)",
        "Schedule, Field Trips, Templates, most of Setup (read-only master data).",
    )
    add_user(
        "driver",
        "driver.jordan",
        "Jordan Rivera (demo)",
        "Driver app: today's runs, stop-by-stop roster, status updates, reports.",
        driver_id=drivers[0]["id"],
    )
    add_user(
        "driver",
        "driver.sam",
        "Sam Okafor (demo)",
        "A second driver's view of the same day.",
        driver_id=drivers[1]["id"],
    )
    add_user(
        "school_admin",
        "school.willowcreek",
        "Riley Principal (demo)",
        "Willow Creek Elementary's buses and notices.",
        school_id=schools[2]["id"],
    )
    parent = add_user(
        "parent",
        "parent.alvarez",
        "Pat Alvarez (demo)",
        "Guardian of Mia (high school) and Emma (elementary): ridership toggles, bus location.",
    )
    for student in (students[0], students[7]):
        post(f"/students/{student['id']}/guardians", {"user_id": parent["id"]})
    add_user(
        "student",
        "student.noah",
        "Noah Bennett (demo)",
        "A high school student's own view.",
        student_id=students[1]["id"],
    )

    return accounts
