from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from isd_api.demo_seed import (
    ADMIN_EMAIL,
    AlreadySeededError,
    create_demo_admin,
    generate_password,
    seed_demo,
)
from tests.conftest import auth_headers, login

START = date(2026, 9, 21)


def _requester(client, headers):
    def request(method: str, path: str, body: dict[str, Any] | None) -> Any:
        response = client.request(method, path, json=body, headers=headers)
        assert response.is_success, f"{method} {path} -> {response.status_code}: {response.text}"
        return response.json() if response.content else None

    return request


@pytest.fixture()
def seeded(client, db_session):
    admin = create_demo_admin(db_session, "admin-pass-123")
    headers = auth_headers(login(client, email=admin.email, password="admin-pass-123"))
    accounts = seed_demo(_requester(client, headers), start_date=START, days=3)
    return headers, [admin, *accounts]


def test_every_role_gets_a_login_that_works(client, seeded):
    _, accounts = seeded
    assert {a.role for a in accounts} == {
        "transportation_admin",
        "dispatcher",
        "driver",
        "school_admin",
        "parent",
        "student",
    }
    assert len({a.email for a in accounts}) == len(accounts)
    for account in accounts:
        token = login(client, email=account.email, password=account.password)
        me = client.get("/users/me", headers=auth_headers(token)).json()
        assert me["role"] == account.role


def test_each_generated_day_is_fully_scheduled(client, seeded):
    headers, _ = seeded
    for day in ("2026-09-21", "2026-09-22", "2026-09-23"):
        assignments = client.get(f"/schedule/{day}/assignments", headers=headers).json()
        # 3 schools x AM/PM, every one covered by a crew.
        assert len(assignments) == 6
    assert client.get("/schedule/2026-09-24/assignments", headers=headers).json() == []


def test_every_route_starts_with_its_stops_planned(client, seeded):
    """So a tester's driver has stops in order, and directions, at once."""
    headers, accounts = seeded
    for route in client.get("/route-templates", headers=headers).json():
        stops = route["stops"]
        assert stops, route
        assert all(s["minutes_from_start"] is not None for s in stops)
        assert max(s["minutes_from_start"] for s in stops) <= route["duration_minutes"]

    sam = next(a for a in accounts if a.email.startswith("driver.sam"))
    driver = auth_headers(login(client, email=sam.email, password=sam.password))
    [first, *_] = client.get("/schedule/2026-09-21/my-assignments", headers=driver).json()
    directions = client.get(
        f"/schedule/assignments/{first['id']}/directions", headers=driver
    ).json()
    # Without a routing engine in tests: the stops in order, then school.
    assert len(directions["waypoints"]) >= 3
    assert "no stops" not in (directions["reason"] or "")


def test_linked_role_views_show_real_data(client, seeded):
    _, accounts = seeded
    by_email = {a.email: a for a in accounts}

    parent = by_email["parent.alvarez@demo.example.org"]
    family = client.get(
        "/students/my-family?service_date=2026-09-21",
        headers=auth_headers(login(client, email=parent.email, password=parent.password)),
    ).json()
    assert sorted(s["full_name"] for s in family) == ["Emma Ibrahim", "Mia Alvarez"]

    school = by_email["school.willowcreek@demo.example.org"]
    buses = client.get(
        "/schedule/2026-09-21/school-assignments",
        headers=auth_headers(login(client, email=school.email, password=school.password)),
    ).json()
    assert len(buses) == 2  # Willow Creek's AM and PM runs


def test_elementary_runs_go_to_the_lift_bus(client, seeded):
    headers, _ = seeded
    vehicles = {v["id"]: v["label"] for v in client.get("/vehicles", headers=headers).json()}
    schools = {s["id"]: s["name"] for s in client.get("/schools", headers=headers).json()}
    runs = {r["id"]: r for r in client.get("/runs?service_date=2026-09-21", headers=headers).json()}
    crews = {
        c["id"]: c for c in client.get("/crews?service_date=2026-09-21", headers=headers).json()
    }
    elementary = [
        a
        for a in client.get("/schedule/2026-09-21/assignments", headers=headers).json()
        if schools[runs[a["run_id"]]["school_id"]] == "Willow Creek Elementary"
    ]
    assert len(elementary) == 2
    for a in elementary:
        assert vehicles[crews[a["crew_id"]]["vehicle_id"]] == "Bus 12 (lift)"


def test_every_standing_crew_driver_has_runs_every_day(client, seeded):
    # Otherwise a tester logging in as a demo driver sees an empty app.
    headers, accounts = seeded
    driver_accounts = [a for a in accounts if a.role == "driver"]
    for account in driver_accounts:
        token = login(client, email=account.email, password=account.password)
        for day in ("2026-09-21", "2026-09-22", "2026-09-23"):
            mine = client.get(f"/schedule/{day}/my-assignments", headers=auth_headers(token))
            assert len(mine.json()) == 2, (account.email, day)  # one AM + one PM run


def test_refuses_to_run_on_a_database_that_already_has_users(db_session, seeded):
    with pytest.raises(AlreadySeededError):
        create_demo_admin(db_session, "another-pass-123")


def test_admin_email_is_the_documented_one(seeded):
    _, accounts = seeded
    assert accounts[0].email == ADMIN_EMAIL


def test_generated_passwords_are_long_and_distinct():
    passwords = {generate_password() for _ in range(50)}
    assert len(passwords) == 50
    assert all(len(p) >= 12 for p in passwords)
