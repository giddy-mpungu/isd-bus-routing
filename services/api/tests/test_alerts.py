"""Operational alerts (spec sections 9, 13.1, 14, 16, 18): what needs
dispatch's attention on a date, derived from live data. The district clock
is America/Chicago (UTC-5 in August); each test sets its own time."""

from datetime import UTC, datetime

import pytest

from isd_api.alerts import (
    ACK_WARNING_MINUTES,
    FINISH_GRACE_MINUTES,
    GPS_STALE_MINUTES,
    START_GRACE_MINUTES,
)
from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user

DAY = "2026-08-01"


@pytest.fixture()
def clock(monkeypatch):
    """clock(minute_of_day) sets the district time on DAY."""

    def set_to(minute: int) -> None:
        moment = datetime(2026, 8, 1, 5, 0, tzinfo=UTC).replace(
            hour=5 + minute // 60, minute=minute % 60
        )
        monkeypatch.setattr("isd_api.ridership_rules.utc_now", lambda: moment)

    return set_to


def _alerts(client, h, day=DAY):
    response = client.get("/alerts", headers=h, params={"service_date": day})
    assert response.status_code == 200, response.text
    return response.json()


def _kinds(client, h, day=DAY):
    return [(a["kind"], a["severity"]) for a in _alerts(client, h, day)["alerts"]]


def _setup(client, h, db_session, *, window=(450, 480), duration=30):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    driver = client.post(
        "/drivers", headers=h, json={"full_name": "Pat Driver", "license_class": "cdl_b"}
    ).json()
    vehicle = client.post("/vehicles", headers=h, json={"label": "Bus 7"}).json()
    crew = client.post(
        "/crews",
        headers=h,
        json={
            "service_date": DAY,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 360,
            "available_window_latest": 1000,
        },
    ).json()
    client.post(
        "/runs",
        headers=h,
        json={
            "service_date": DAY,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": window[0],
            "window_latest": window[1],
            "duration_minutes": duration,
        },
    )
    [assignment] = client.post("/schedule", headers=h, json={"service_date": DAY}).json()[
        "assignments"
    ]
    make_user(db_session, email="pat@example.org", role=Role.DRIVER, driver_id=driver["id"])
    pat = auth_headers(login(client, email="pat@example.org"))
    return {
        "school": school,
        "driver": driver,
        "vehicle": vehicle,
        "crew": crew,
        "assignment": assignment,
        "pat": pat,
    }


def _move(client, day, status):
    return client.patch(
        f"/schedule/assignments/{day['assignment']['id']}/status",
        headers=day["pat"],
        json={"status": status},
    )


def test_a_quiet_day_has_no_alerts_and_reports_the_district_time(client, admin_headers, clock):
    clock(7 * 60 + 5)
    body = _alerts(client, admin_headers)
    assert body == {"service_date": DAY, "district_time": "07:05", "alerts": []}
    assert _alerts(client, admin_headers, "2026-08-02")["district_time"] is None


def test_only_dispatch_can_see_alerts(client, admin_headers, db_session):
    make_user(db_session, email="d@example.org", role=Role.DISPATCHER)
    make_user(db_session, email="s@example.org", role=Role.SCHOOL_ADMIN)
    dispatcher = auth_headers(login(client, email="d@example.org"))
    school_admin = auth_headers(login(client, email="s@example.org"))
    params = {"service_date": DAY}
    assert client.get("/alerts", headers=dispatcher, params=params).status_code == 200
    assert client.get("/alerts", headers=school_admin, params=params).status_code == 403


def test_a_run_with_no_bus_is_critical(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    run = client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": DAY,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 450,
            "window_latest": 480,
            "duration_minutes": 30,
        },
    ).json()
    [alert] = _alerts(client, admin_headers)["alerts"]
    assert (alert["kind"], alert["severity"]) == ("unassigned_run", "critical")
    assert alert["message"] == "No bus assigned to Riverside AM run (07:30-08:00)"
    assert (alert["entity_type"], alert["entity_id"]) == ("run", run["id"])


def test_an_absence_after_scheduling_raises_needs_cover(client, admin_headers, db_session, clock):
    clock(6 * 60)
    day = _setup(client, admin_headers, db_session)
    client.post(
        f"/drivers/{day['driver']['id']}/absences",
        headers=admin_headers,
        json={"service_date": DAY, "start_minute": 0, "end_minute": 1439, "reason": "sick_leave"},
    )
    [alert] = _alerts(client, admin_headers)["alerts"]
    assert (alert["kind"], alert["severity"]) == ("needs_cover", "critical")
    assert "Riverside AM run on Bus 7" in alert["message"]
    assert "driver absent (sick leave" in alert["message"]


def test_unacknowledged_work_warns_as_its_start_nears(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]

    clock(start - ACK_WARNING_MINUTES - 1)
    assert _kinds(client, admin_headers) == []
    clock(start - ACK_WARNING_MINUTES)
    [alert] = _alerts(client, admin_headers)["alerts"]
    assert (alert["kind"], alert["severity"]) == ("not_acknowledged", "warning")
    assert alert["message"].startswith("Pat Driver hasn't acknowledged Riverside AM run")

    _move(client, day, "acknowledged")
    assert _kinds(client, admin_headers) == []


def test_work_not_started_after_the_grace_period_is_critical(
    client, admin_headers, db_session, clock
):
    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]
    _move(client, day, "acknowledged")

    clock(start + START_GRACE_MINUTES - 1)
    assert _kinds(client, admin_headers) == []
    clock(start + START_GRACE_MINUTES)
    [alert] = _alerts(client, admin_headers)["alerts"]
    assert (alert["kind"], alert["severity"]) == ("late_start", "critical")
    assert "still acknowledged" in alert["message"]


def test_unacknowledged_and_late_gives_one_alert_not_two(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    clock(day["assignment"]["start_minute"] + START_GRACE_MINUTES + 5)
    assert _kinds(client, admin_headers) == [("late_start", "critical")]


def test_work_running_past_its_end_warns(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    end = day["assignment"]["end_minute"]
    _move(client, day, "in_progress")

    clock(end + FINISH_GRACE_MINUTES - 1)
    assert ("overrunning", "warning") not in _kinds(client, admin_headers)
    clock(end + FINISH_GRACE_MINUTES)
    assert ("overrunning", "warning") in _kinds(client, admin_headers)
    _move(client, day, "completed")
    assert _kinds(client, admin_headers) == []


def test_a_bus_under_way_that_stops_reporting_gps_warns(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]
    clock(start)
    _move(client, day, "en_route")
    [alert] = _alerts(client, admin_headers)["alerts"]
    assert alert["kind"] == "no_gps"
    assert alert["message"].startswith("No GPS from Bus 7 yet")

    reported = datetime(2026, 8, 1, 5 + start // 60, start % 60, tzinfo=UTC)
    client.put(
        f"/drivers/{day['driver']['id']}/position",
        headers=day["pat"],
        json={
            "service_date": DAY,
            "location_lat": 29.7,
            "location_lon": -95.4,
            "recorded_at": reported.isoformat(),
        },
    )
    assert _kinds(client, admin_headers) == []
    clock(start + GPS_STALE_MINUTES)
    [stale] = _alerts(client, admin_headers)["alerts"]
    assert stale["message"].startswith(f"No GPS from Bus 7 for {GPS_STALE_MINUTES} min")


def test_no_show_is_critical_and_finished_work_is_quiet(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    clock(day["assignment"]["end_minute"] + 60)
    _move(client, day, "no_show")
    assert _kinds(client, admin_headers) == [("no_show", "critical")]


def test_dispatch_tasks_get_the_same_timing_alerts_unless_cancelled(
    client, admin_headers, db_session, clock
):
    driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Sam", "license_class": "cdl_b"}
    ).json()
    task = client.post(
        "/dispatch-tasks",
        headers=admin_headers,
        json={
            "kind": "move_vehicle",
            "service_date": DAY,
            "start_minute": 600,
            "end_minute": 630,
            "driver_id": driver["id"],
            "instructions": "Take Bus 9 to the shop.",
        },
    ).json()
    clock(600 + START_GRACE_MINUTES)
    [alert] = _alerts(client, admin_headers)["alerts"]
    assert (alert["kind"], alert["entity_type"], alert["entity_id"]) == (
        "late_start",
        "dispatch_task",
        task["id"],
    )
    assert alert["message"].startswith(f"Dispatch task #{task['id']} (move vehicle) hasn't started")

    client.post(f"/dispatch-tasks/{task['id']}/cancel", headers=admin_headers)
    assert _kinds(client, admin_headers) == []


def _trip(client, h, depart="09:00", back="13:30"):
    return client.post(
        "/field-trips",
        headers=h,
        json={
            "requesting_party": "Grade 5",
            "origin": "Riverside",
            "destination": "Science Museum",
            "departure_at": f"{DAY}T{depart}:00",
            "expected_return_at": f"{DAY}T{back}:00",
            "trip_contact": "Ms. Patel",
        },
    ).json()


def test_a_field_trip_leaving_today_without_a_driver_or_bus_is_critical(
    client, admin_headers, clock
):
    clock(7 * 60)
    trip = _trip(client, admin_headers)
    [alert] = _alerts(client, admin_headers)["alerts"]
    assert (alert["kind"], alert["severity"]) == ("unstaffed_trip", "critical")
    assert alert["message"] == (
        f"Field trip #{trip['id']} to Science Museum departs at 09:00 "
        "with no driver or bus assigned"
    )
    driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Sam", "license_class": "cdl_b"}
    ).json()
    bus = client.post("/vehicles", headers=admin_headers, json={"label": "Bus 9"}).json()
    client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"assigned_driver_id": driver["id"]},
    )
    assert "with no bus assigned" in _alerts(client, admin_headers)["alerts"][0]["message"]
    client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"assigned_vehicle_id": bus["id"]},
    )
    assert _kinds(client, admin_headers) == []


def test_a_trip_past_its_return_with_none_recorded_warns(client, admin_headers, clock):
    trip = _trip(client, admin_headers, "09:00", "13:30")
    driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Sam", "license_class": "cdl_b"}
    ).json()
    bus = client.post("/vehicles", headers=admin_headers, json={"label": "Bus 9"}).json()
    client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"assigned_driver_id": driver["id"], "assigned_vehicle_id": bus["id"]},
    )
    clock(13 * 60 + 30 + FINISH_GRACE_MINUTES - 1)
    assert _kinds(client, admin_headers) == []
    clock(13 * 60 + 30 + FINISH_GRACE_MINUTES)
    [alert] = _alerts(client, admin_headers)["alerts"]
    assert (alert["kind"], alert["severity"]) == ("overdue_trip", "warning")
    assert "was due back at 13:30" in alert["message"]

    client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"actual_return_at": f"{DAY}T13:40:00"},
    )
    assert _kinds(client, admin_headers) == []


def test_driver_reports_raise_alerts_incidents_first(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    clock(6 * 60)
    for report_type, text in (("vehicle_defect", "Left mirror cracked"), ("incident", "x" * 200)):
        client.post(
            f"/drivers/{day['driver']['id']}/reports",
            headers=day["pat"],
            json={"service_date": DAY, "report_type": report_type, "description": text},
        )
    alerts = _alerts(client, admin_headers)["alerts"]
    assert [(a["kind"], a["severity"]) for a in alerts] == [
        ("incident", "critical"),
        ("vehicle_defect", "warning"),
    ]
    assert alerts[0]["message"].startswith("Incident reported by Pat Driver, Bus 7: xxx")
    assert alerts[0]["message"].endswith("...")
    assert len(alerts[0]["message"]) < 200
    assert (
        alerts[1]["message"] == "Vehicle defect reported by Pat Driver, Bus 7: Left mirror cracked"
    )


def test_a_past_day_shows_what_never_happened_and_a_future_day_no_timing(
    client, admin_headers, db_session, clock, monkeypatch
):
    _setup(client, admin_headers, db_session)
    clock(6 * 60)  # DAY is today, well before the run
    assert _kinds(client, admin_headers) == []

    def at(moment):
        monkeypatch.setattr("isd_api.ridership_rules.utc_now", lambda: moment)

    # The next morning, the run that never started is still flagged.
    at(datetime(2026, 8, 2, 12, 0, tzinfo=UTC))
    assert _kinds(client, admin_headers) == [("late_start", "critical")]
    # Days ahead of DAY: nothing time-based yet.
    at(datetime(2026, 7, 30, 12, 0, tzinfo=UTC))
    assert _kinds(client, admin_headers) == []


def test_critical_alerts_come_before_warnings(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    clock(day["assignment"]["start_minute"] - 5)  # not acknowledged: a warning
    client.post(
        f"/drivers/{day['driver']['id']}/reports",
        headers=day["pat"],
        json={"service_date": DAY, "report_type": "incident", "description": "Minor scrape"},
    )
    assert [s for _, s in _kinds(client, admin_headers)] == ["critical", "warning"]
