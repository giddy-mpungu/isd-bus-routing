"""Ridership reporting rules (spec sections 4.4, 4.5): a district time zone
and cutoffs, no changes to past days, and no requests to ride a full bus."""

from datetime import UTC, datetime

import pytest

from isd_api.models import AuditLogEntry, Role, User
from tests.conftest import auth_headers, login, make_user

DAY = "2026-10-05"
# 12:00 UTC on DAY = 07:00 in Chicago (CDT) = 05:00 in Los Angeles (PDT).
NOON_UTC = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


@pytest.fixture()
def at_noon_utc(monkeypatch):
    monkeypatch.setattr("isd_api.ridership_rules.utc_now", lambda: NOON_UTC)


def _rules(client, h, *, tz="America/Chicago", am=None, pm=None):
    return client.put(
        "/ridership-rules",
        headers=h,
        json={"timezone": tz, "am_cutoff_minute": am, "pm_cutoff_minute": pm},
    )


def _school(client, h):
    return client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside Elementary", "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _student(client, h, school, name, default="rides"):
    return client.post(
        "/students",
        headers=h,
        json={"full_name": name, "school_id": school["id"], "default_ridership": default},
    ).json()


def _parent_of(client, h, db_session, student, email="parent@example.org"):
    make_user(db_session, email=email, role=Role.PARENT)
    user = db_session.query(User).filter(User.email == email).one()
    client.post(f"/students/{student['id']}/guardians", headers=h, json={"user_id": user.id})
    return auth_headers(login(client, email=email))


def _declare(client, h, student, *, day=DAY, direction="am", riding=True):
    return client.patch(
        f"/students/{student['id']}/ridership",
        headers=h,
        json={"service_date": day, "direction": direction, "is_riding": riding},
    )


# --- Configuring the rules ----------------------------------------------------


def test_defaults_are_the_district_time_zone_and_no_cutoffs(client, admin_headers):
    assert client.get("/ridership-rules", headers=admin_headers).json() == {
        "timezone": "America/Chicago",
        "am_cutoff_minute": None,
        "pm_cutoff_minute": None,
        "is_default": True,
    }


def test_rules_round_trip_are_audited_and_validated(client, admin_headers, db_session):
    response = _rules(client, admin_headers, tz="America/New_York", am=360, pm=720)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "timezone": "America/New_York",
        "am_cutoff_minute": 360,
        "pm_cutoff_minute": 720,
        "is_default": False,
    }
    entry = (
        db_session.query(AuditLogEntry).filter(AuditLogEntry.entity_type == "ridership_rules").one()
    )
    assert entry.after_state["am_cutoff_minute"] == 360

    assert _rules(client, admin_headers, tz="Mars/Olympus_Mons").status_code == 422
    assert _rules(client, admin_headers, am=1440).status_code == 422


def test_dispatchers_can_read_but_not_change_the_rules(client, admin_headers, db_session):
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="disp@example.org"))
    assert client.get("/ridership-rules", headers=dispatcher).status_code == 200
    assert _rules(client, dispatcher, am=360).status_code == 403


# --- Families and the clock ---------------------------------------------------


def test_families_cannot_change_a_past_day(client, admin_headers, db_session, at_noon_utc):
    student = _student(client, admin_headers, _school(client, admin_headers), "Jamie")
    parent = _parent_of(client, admin_headers, db_session, student)

    response = _declare(client, parent, student, day="2026-10-04", riding=False)
    assert response.status_code == 409
    assert "past day" in response.json()["detail"]
    assert _declare(client, parent, student, day="2026-10-06", riding=False).status_code == 204


def test_the_cutoff_closes_today_for_that_leg_only(client, admin_headers, db_session, at_noon_utc):
    # It's 07:00 in Chicago: past the 06:00 AM cutoff, before the 12:00 PM one.
    _rules(client, admin_headers, am=360, pm=720)
    student = _student(client, admin_headers, _school(client, admin_headers), "Jamie")
    parent = _parent_of(client, admin_headers, db_session, student)

    am = _declare(client, parent, student, direction="am", riding=False)
    assert am.status_code == 409
    assert "closed at 06:00" in am.json()["detail"]
    assert _declare(client, parent, student, direction="pm", riding=False).status_code == 204


def test_the_cutoff_uses_the_district_time_zone(client, admin_headers, db_session, at_noon_utc):
    # The same instant is only 05:00 in Los Angeles, before a 06:00 cutoff.
    _rules(client, admin_headers, tz="America/Los_Angeles", am=360)
    student = _student(client, admin_headers, _school(client, admin_headers), "Jamie")
    parent = _parent_of(client, admin_headers, db_session, student)
    assert _declare(client, parent, student, riding=False).status_code == 204


def test_staff_can_still_record_a_late_change(client, admin_headers, at_noon_utc):
    _rules(client, admin_headers, am=360)
    student = _student(client, admin_headers, _school(client, admin_headers), "Jamie")
    assert _declare(client, admin_headers, student, riding=False).status_code == 204
    assert _declare(client, admin_headers, student, day="2026-10-01").status_code == 204


def test_my_family_says_which_legs_are_closed(client, admin_headers, db_session, at_noon_utc):
    _rules(client, admin_headers, am=360, pm=720)
    student = _student(client, admin_headers, _school(client, admin_headers), "Jamie")
    parent = _parent_of(client, admin_headers, db_session, student)

    [today] = client.get("/students/my-family", headers=parent, params={"service_date": DAY}).json()
    assert "closed at 06:00" in today["am_changes_closed"]
    assert today["pm_changes_closed"] is None

    [tomorrow] = client.get(
        "/students/my-family", headers=parent, params={"service_date": "2026-10-06"}
    ).json()
    assert tomorrow["am_changes_closed"] is None and tomorrow["pm_changes_closed"] is None


# --- A full bus (spec 4.5) ----------------------------------------------------


def _full_bus_day(client, h, *, runs=1):
    """Two default riders on a 2-seat bus, plus a third student who
    normally doesn't ride."""
    school = _school(client, h)
    riders = [_student(client, h, school, name) for name in ("Ava", "Ben")]
    occasional = _student(client, h, school, "Cai", default="does_not_ride")
    for label in [str(i) for i in range(runs)]:
        driver = client.post(
            "/drivers", headers=h, json={"license_class": "cdl_a", "full_name": f"D{label}"}
        ).json()
        vehicle = client.post(
            "/vehicles",
            headers=h,
            json={"label": f"Van {label}", "nominal_capacity": 2, "effective_capacity": 2},
        ).json()
        client.post(
            "/crews",
            headers=h,
            json={
                "service_date": DAY,
                "driver_id": driver["id"],
                "vehicle_id": vehicle["id"],
                "available_window_earliest": 360,
                "available_window_latest": 1000,
            },
        )
        client.post(
            "/runs",
            headers=h,
            json={
                "service_date": DAY,
                "school_id": school["id"],
                "direction": "am",
                "window_earliest": 420,
                "window_latest": 480,
                "duration_minutes": 30,
            },
        )
    assert client.post("/schedule", headers=h, json={"service_date": DAY}).status_code == 200
    return riders, occasional


def test_a_request_to_ride_a_full_bus_is_refused(client, admin_headers, db_session):
    riders, occasional = _full_bus_day(client, admin_headers)
    parent = _parent_of(client, admin_headers, db_session, occasional)

    response = _declare(client, parent, occasional)
    assert response.status_code == 409
    assert "is full (2 of 2 seats)" in response.json()["detail"]

    # Once a regular rider drops out, there's room.
    assert _declare(client, admin_headers, riders[0], riding=False).status_code == 204
    assert _declare(client, parent, occasional).status_code == 204


def test_saying_you_wont_ride_is_never_blocked_by_capacity(client, admin_headers, db_session):
    riders, _ = _full_bus_day(client, admin_headers)
    parent = _parent_of(client, admin_headers, db_session, riders[0])
    assert _declare(client, parent, riders[0], riding=False).status_code == 204


def test_a_rider_already_counted_can_confirm_without_being_refused(
    client, admin_headers, db_session
):
    riders, _ = _full_bus_day(client, admin_headers)
    parent = _parent_of(client, admin_headers, db_session, riders[0])
    assert _declare(client, parent, riders[0], riding=True).status_code == 204


def test_capacity_isnt_guessed_when_several_runs_serve_the_leg(client, admin_headers, db_session):
    _, occasional = _full_bus_day(client, admin_headers, runs=2)
    parent = _parent_of(client, admin_headers, db_session, occasional)
    assert _declare(client, parent, occasional).status_code == 204
