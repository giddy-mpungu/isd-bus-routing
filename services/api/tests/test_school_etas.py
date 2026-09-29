"""When each bus is expected at the school (spec section 17's "expected
arrivals" and "delayed buses" for school administrators). The district
clock is America/Chicago, UTC-5 in October; each test sets its own time."""

from datetime import UTC, datetime, timedelta

import pytest

from isd_api.models import Assignment, Role
from tests.conftest import auth_headers, login, make_user
from tests.test_route_stops import _crew, _set_stops, _stop, _student

DAY = "2026-10-05"  # a Monday


@pytest.fixture()
def clock(monkeypatch):
    def set_to(minute: int, day: int = 5) -> datetime:
        moment = datetime(2026, 10, day, tzinfo=UTC) + timedelta(minutes=minute + 5 * 60)
        monkeypatch.setattr("isd_api.ridership_rules.utc_now", lambda: moment)
        return moment

    return set_to


def _setup(client, h, db_session, direction="am"):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    far = _stop(client, h, "Far", 29.74)
    near = _stop(client, h, "Near", 29.71)
    window = (420, 500) if direction == "am" else (900, 980)
    route = client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": direction,
            "window_earliest": window[0],
            "window_latest": window[1],
            "duration_minutes": 40,
            "days_of_week": [0, 1, 2, 3, 4],
        },
    ).json()
    _set_stops(client, h, route, (far, None), (near, None))
    _student(client, h, school, "Ana", far)
    _student(client, h, school, "Cy", near)
    client.post(f"/route-templates/{route['id']}/stops/plan", headers=h, json={"apply": True})
    driver, driver_headers = _crew(client, h, "A", db_session)
    client.post(f"/schedule/{DAY}/generate-from-templates", headers=h)
    [assignment] = client.post("/schedule", headers=h, json={"service_date": DAY}).json()[
        "assignments"
    ]
    make_user(
        db_session, email="office@example.org", role=Role.SCHOOL_ADMIN, school_id=school["id"]
    )
    office = auth_headers(login(client, email="office@example.org"))
    return {
        "assignment": assignment,
        "driver": driver,
        "driver_headers": driver_headers,
        "office": office,
        "far": far,
    }


def _bus(client, day):
    [bus] = client.get(f"/schedule/{DAY}/school-assignments", headers=day["office"]).json()
    return bus


def _move(client, day, status):
    response = client.patch(
        f"/schedule/assignments/{day['assignment']['id']}/status",
        headers=day["driver_headers"],
        json={"status": status},
    )
    assert response.status_code == 200, response.text


def _gps(client, day, lat, lon, at):
    response = client.put(
        f"/drivers/{day['driver']['id']}/position",
        headers=day["driver_headers"],
        json={
            "service_date": DAY,
            "location_lat": lat,
            "location_lon": lon,
            "recorded_at": at.isoformat(),
        },
    )
    assert response.status_code == 204, response.text


def test_before_the_run_starts_the_morning_arrival_is_the_plan(
    client, admin_headers, db_session, clock
):
    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]
    clock(start - 30)
    bus = _bus(client, day)
    run = client.get("/runs", headers=admin_headers, params={"service_date": DAY}).json()[0]
    assert bus["planned_school_minute"] == start + run["duration_minutes"]
    assert bus["expected_school_minute"] == bus["planned_school_minute"]
    assert (bus["delay_minutes"], bus["running_late"], bus["eta_basis"]) == (0, False, "On plan")


def test_a_bus_that_has_not_started_is_late_by_the_time_since(
    client, admin_headers, db_session, clock
):
    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]
    clock(start + 3)
    bus = _bus(client, day)
    assert (bus["delay_minutes"], bus["running_late"], bus["eta_basis"]) == (
        3,
        False,
        "Not started yet",
    )
    clock(start + 12)
    bus = _bus(client, day)
    assert (bus["delay_minutes"], bus["running_late"]) == (12, True)


def test_under_way_the_estimate_follows_the_buses_gps(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]
    now = clock(start)
    _move(client, day, "en_route")

    # At the first stop on time: arriving about as planned.
    _gps(client, day, day["far"]["location_lat"], day["far"]["location_lon"], now)
    on_time = _bus(client, day)
    assert on_time["eta_basis"] == "Live GPS"
    assert on_time["delay_minutes"] <= 2

    # Twenty minutes later and still ten miles out: running late.
    now = clock(start + 20)
    _gps(client, day, 29.70 + 10 / 69.09, -95.40, now)
    late = _bus(client, day)
    assert late["eta_basis"] == "Live GPS"
    assert late["running_late"] is True and late["delay_minutes"] >= 20


def test_a_very_late_bus_still_counts_the_stops_ahead_of_it(
    client, admin_headers, db_session, clock
):
    # An hour late, at the first stop: every planned stop time has passed,
    # but both stops are still ahead, so the estimate includes them.
    from isd_solver import Location, straight_line_travel_seconds

    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]
    now = clock(start + 60)
    _move(client, day, "en_route")
    far = day["far"]
    _gps(client, day, far["location_lat"], far["location_lon"], now)
    bus = _bus(client, day)
    straight = straight_line_travel_seconds()(
        Location(far["location_lat"], far["location_lon"]), Location(29.70, -95.40)
    )
    # Loading at both stops on top of the drive.
    assert bus["expected_school_minute"] - (start + 60) >= round(straight / 60) + 2


def test_stale_gps_does_not_count_as_live(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]
    then = clock(start)
    _move(client, day, "en_route")
    _gps(client, day, 29.9, -95.40, then)
    clock(start + 10)
    assert _bus(client, day)["eta_basis"] == "On plan"


def test_a_completed_morning_run_shows_when_it_actually_arrived(
    client, admin_headers, db_session, clock
):
    day = _setup(client, admin_headers, db_session)
    start = day["assignment"]["start_minute"]
    clock(start + 60)
    _move(client, day, "completed")
    row = db_session.get(Assignment, day["assignment"]["id"])
    row.status_updated_at = datetime(2026, 10, 5, tzinfo=UTC) + timedelta(
        minutes=start + 47 + 5 * 60
    )
    db_session.commit()
    bus = _bus(client, day)
    assert (bus["eta_basis"], bus["expected_school_minute"]) == ("Arrived", start + 47)
    assert bus["delay_minutes"] == start + 47 - bus["planned_school_minute"]


def test_the_afternoon_is_about_leaving_school_on_time(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session, direction="pm")
    start = day["assignment"]["start_minute"]
    clock(start + 8)
    bus = _bus(client, day)
    assert bus["planned_school_minute"] == start
    assert (bus["delay_minutes"], bus["running_late"], bus["eta_basis"]) == (
        8,
        True,
        "Not started yet",
    )
    _move(client, day, "en_route")
    bus = _bus(client, day)
    assert (bus["eta_basis"], bus["delay_minutes"]) == ("Left school", 0)


def test_another_day_shows_only_the_plan(client, admin_headers, db_session, clock):
    day = _setup(client, admin_headers, db_session)
    clock(day["assignment"]["start_minute"] + 30, day=4)  # the day before
    bus = _bus(client, day)
    assert (bus["eta_basis"], bus["delay_minutes"]) == ("Planned", 0)
