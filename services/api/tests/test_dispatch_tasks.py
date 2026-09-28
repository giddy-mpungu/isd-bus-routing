"""Dispatch tasks (spec sections 11 and 14): unplanned work dispatch sends
to a driver's tablet. A task follows the assignment lifecycle and is busy
time for its driver and vehicle everywhere work is assigned."""

import pytest

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user
from tests.test_field_trip_scheduling import (
    DAY,
    _assign,
    _assignments,
    _by_run,
    _crew,
    _driver,
    _run,
    _school,
    _solve,
    _trip,
    _vehicle,
)


def _task(client, h, driver, start=540, end=600, *, vehicle=None, kind="assist_disabled_bus"):
    body = {
        "kind": kind,
        "service_date": DAY,
        "start_minute": start,
        "end_minute": end,
        "driver_id": driver["id"],
        "instructions": "Bus 12 is down at Oak & 5th. Pick up its riders.",
        "location": "Oak St & 5th Ave",
    }
    if vehicle is not None:
        body["vehicle_id"] = vehicle["id"]
    return client.post("/dispatch-tasks", headers=h, json=body)


def _driver_login(client, db_session, driver, email):
    make_user(db_session, email=email, role=Role.DRIVER, driver_id=driver["id"])
    return auth_headers(login(client, email=email))


def _audits(db_session, task_id, action=None):
    query = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.entity_type == "dispatch_task", AuditLogEntry.entity_id == task_id
    )
    if action is not None:
        query = query.filter(AuditLogEntry.action == action)
    return query.order_by(AuditLogEntry.id).all()


# --- Creating tasks ----------------------------------------------------------


def test_dispatch_creates_a_task_and_it_is_sent_and_audited(client, admin_headers, db_session):
    driver = _driver(client, admin_headers, "Pat Driver")
    bus = _vehicle(client, admin_headers, "Bus 30")
    response = _task(client, admin_headers, driver, vehicle=bus)
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["status"] == "sent"
    assert task["cancelled"] is False
    assert task["driver_full_name"] == "Pat Driver"
    assert task["vehicle_label"] == "Bus 30"
    assert task["routes_needing_cover"] == []

    [created] = _audits(db_session, task["id"], "created")
    assert created.after_state["kind"] == "assist_disabled_bus"

    [listed] = client.get(
        "/dispatch-tasks", headers=admin_headers, params={"service_date": DAY}
    ).json()
    assert listed["id"] == task["id"]


def test_dispatchers_can_create_tasks_but_drivers_cannot(client, admin_headers, db_session):
    driver = _driver(client, admin_headers, "Pat")
    make_user(db_session, email="dispatch@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="dispatch@example.org"))
    assert _task(client, dispatcher, driver).status_code == 201
    driver_headers = _driver_login(client, db_session, driver, "pat@example.org")
    assert _task(client, driver_headers, driver).status_code == 403
    assert (
        client.get("/dispatch-tasks", headers=driver_headers, params={"service_date": DAY})
    ).status_code == 403


def test_a_task_needs_a_real_window_and_real_resources(client, admin_headers):
    driver = _driver(client, admin_headers, "Pat")
    assert _task(client, admin_headers, driver, 600, 600).status_code == 400
    assert _task(client, admin_headers, {"id": 9999}).status_code == 400
    assert _task(client, admin_headers, driver, vehicle={"id": 9999}).status_code == 400


@pytest.mark.parametrize("problem", ["absent", "deactivated", "out_of_service", "unlicensed"])
def test_a_driver_or_bus_that_cannot_work_refuses_the_task(client, admin_headers, problem):
    driver = _driver(client, admin_headers, "Pat")
    bus = _vehicle(client, admin_headers, "Bus 30")
    expected = {
        "absent": "absent",
        "deactivated": "deactivated",
        "out_of_service": "out of service",
        "unlicensed": "isn't licensed",
    }[problem]
    if problem == "absent":
        client.post(
            f"/drivers/{driver['id']}/absences",
            headers=admin_headers,
            json={
                "service_date": DAY,
                "start_minute": 500,
                "end_minute": 560,
                "reason": "sick_leave",
            },
        )
    elif problem == "deactivated":
        client.patch(f"/drivers/{driver['id']}", headers=admin_headers, json={"is_active": False})
    elif problem == "out_of_service":
        client.patch(f"/vehicles/{bus['id']}", headers=admin_headers, json={"is_active": False})
    else:
        client.patch(
            f"/drivers/{driver['id']}", headers=admin_headers, json={"license_class": "class_c"}
        )

    response = _task(client, admin_headers, driver, vehicle=bus)
    assert response.status_code == 409, response.text
    assert expected in response.json()["detail"]


def test_overlapping_tasks_for_the_same_driver_or_bus_are_refused(client, admin_headers):
    driver = _driver(client, admin_headers, "Pat")
    other = _driver(client, admin_headers, "Sam")
    bus = _vehicle(client, admin_headers, "Bus 30")
    first = _task(client, admin_headers, driver, 540, 600, vehicle=bus).json()

    same_driver = _task(client, admin_headers, driver, 570, 630)
    assert same_driver.status_code == 409
    assert f"dispatch task #{first['id']}" in same_driver.json()["detail"]
    same_bus = _task(client, admin_headers, other, 570, 630, vehicle=bus)
    assert same_bus.status_code == 409
    # Back to back is fine.
    assert _task(client, admin_headers, driver, 600, 660).status_code == 201


def test_a_task_cannot_overlap_the_drivers_field_trip(client, admin_headers):
    driver = _driver(client, admin_headers, "Pat")
    trip = _trip(client, admin_headers, "09:00", "13:30")
    assert _assign(client, admin_headers, trip, driver=driver).status_code == 200
    response = _task(client, admin_headers, driver, 600, 660)
    assert response.status_code == 409
    assert f"Field trip #{trip['id']}" in response.json()["detail"]


def test_a_field_trip_cannot_be_given_to_a_driver_busy_on_a_task(client, admin_headers):
    driver = _driver(client, admin_headers, "Pat")
    task = _task(client, admin_headers, driver, 600, 660).json()
    trip = _trip(client, admin_headers, "09:00", "13:30")
    response = _assign(client, admin_headers, trip, driver=driver)
    assert response.status_code == 409
    assert f"Dispatch task #{task['id']}" in response.json()["detail"]


# --- Busy time ---------------------------------------------------------------


def test_the_solver_keeps_a_tasked_driver_off_overlapping_runs(client, admin_headers):
    # Crew A can do both runs alone (the unique best plan). Once A's driver
    # has an afternoon task, the 14:15 run must go to C.
    school = _school(client, admin_headers)
    a_driver, _, a_crew = _crew(client, admin_headers, "A")
    _crew(client, admin_headers, "B", latest=600)
    _, _, c_crew = _crew(client, admin_headers, "C", earliest=800)
    _run(client, admin_headers, school, 400, 440)
    afternoon = _run(client, admin_headers, school, 855, 900)
    assert set(_by_run(_solve(client, admin_headers)).values()) == {a_crew["id"]}

    assert _task(client, admin_headers, a_driver, 840, 960).status_code == 201

    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert _by_run(response)[afternoon["id"]] == c_crew["id"]


def test_a_task_also_holds_its_bus(client, admin_headers):
    school = _school(client, admin_headers)
    _, a_bus, a_crew = _crew(client, admin_headers, "A")
    _crew(client, admin_headers, "B", latest=600)
    _, _, c_crew = _crew(client, admin_headers, "C", earliest=800)
    _run(client, admin_headers, school, 400, 440)
    afternoon = _run(client, admin_headers, school, 855, 900)
    assert set(_by_run(_solve(client, admin_headers)).values()) == {a_crew["id"]}

    mover = _driver(client, admin_headers, "Yard Driver")
    moved = _task(client, admin_headers, mover, 840, 960, vehicle=a_bus, kind="move_vehicle")
    assert moved.status_code == 201, moved.text

    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert _by_run(response)[afternoon["id"]] == c_crew["id"]


def test_a_task_over_a_planned_run_is_allowed_and_flags_the_run_for_cover(client, admin_headers):
    # An emergency takes priority over the plan; the run it pulls the driver
    # off is shown as needing cover, and cancelling the task clears that.
    school = _school(client, admin_headers)
    driver, _, crew = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 420, 480)
    [assignment] = _solve(client, admin_headers).json()["assignments"]
    assert assignment["crew_id"] == crew["id"]

    response = _task(client, admin_headers, driver, 400, 470, kind="emergency")
    assert response.status_code == 201, response.text
    task = response.json()
    [needs_cover] = task["routes_needing_cover"]
    assert needs_cover.startswith("Riverside AM run on Bus A")

    [flagged] = _assignments(client, admin_headers)
    assert flagged["availability_issue"].startswith(f"on dispatch task #{task['id']} (emergency")

    cancelled = client.post(f"/dispatch-tasks/{task['id']}/cancel", headers=admin_headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["cancelled"] is True
    assert cancelled.json()["routes_needing_cover"] == []
    [cleared] = _assignments(client, admin_headers)
    assert cleared["availability_issue"] is None


def test_manual_reassignment_onto_a_tasked_driver_is_rejected(client, admin_headers):
    school = _school(client, admin_headers)
    _crew(client, admin_headers, "A")
    tasked, _, tasked_crew = _crew(client, admin_headers, "B")
    _task(client, admin_headers, tasked, 400, 500)
    _run(client, admin_headers, school, 420, 480)
    [assignment] = _solve(client, admin_headers).json()["assignments"]
    assert assignment["crew_id"] != tasked_crew["id"]

    response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"crew_id": tasked_crew["id"]},
    )
    assert response.status_code == 422
    assert "dispatch task" in response.json()["detail"]


def test_substitute_ranking_leaves_out_drivers_busy_on_a_task(client, admin_headers):
    school = _school(client, admin_headers)
    driver, _, _ = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 420, 480)
    _solve(client, admin_headers)
    free = _driver(client, admin_headers, "Free Sub")
    busy = _driver(client, admin_headers, "Tasked Sub")
    _task(client, admin_headers, busy, 400, 500)

    [affected] = client.get(
        f"/drivers/{driver['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": DAY},
    ).json()
    ids = {c["driver_id"] for c in affected["candidates"]}
    assert free["id"] in ids and busy["id"] not in ids


# --- Editing and cancelling --------------------------------------------------


def test_moving_a_task_rechecks_conflicts_before_changing_anything(client, admin_headers):
    driver = _driver(client, admin_headers, "Pat")
    first = _task(client, admin_headers, driver, 540, 600).json()
    second = _task(client, admin_headers, driver, 660, 720).json()

    clash = client.patch(
        f"/dispatch-tasks/{second['id']}", headers=admin_headers, json={"start_minute": 580}
    )
    assert clash.status_code == 409
    [unchanged] = [
        t
        for t in client.get(
            "/dispatch-tasks", headers=admin_headers, params={"service_date": DAY}
        ).json()
        if t["id"] == second["id"]
    ]
    assert unchanged["start_minute"] == 660

    # A task doesn't conflict with itself.
    moved = client.patch(
        f"/dispatch-tasks/{first['id']}", headers=admin_headers, json={"end_minute": 620}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["end_minute"] == 620


def test_handing_an_unstarted_task_to_another_driver_sends_it_again(
    client, admin_headers, db_session
):
    driver = _driver(client, admin_headers, "Pat")
    other = _driver(client, admin_headers, "Sam")
    task = _task(client, admin_headers, driver).json()
    pat = _driver_login(client, db_session, driver, "pat@example.org")
    client.patch(
        f"/dispatch-tasks/{task['id']}/status", headers=pat, json={"status": "acknowledged"}
    )

    moved = client.patch(
        f"/dispatch-tasks/{task['id']}", headers=admin_headers, json={"driver_id": other["id"]}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "sent"
    assert moved.json()["driver_full_name"] == "Sam"
    [updated] = _audits(db_session, task["id"], "updated")
    assert updated.before_state["driver_id"] == driver["id"]
    assert updated.after_state["driver_id"] == other["id"]


def test_dispatch_can_clear_the_vehicle_and_correct_the_state(client, admin_headers):
    driver = _driver(client, admin_headers, "Pat")
    bus = _vehicle(client, admin_headers, "Bus 30")
    task = _task(client, admin_headers, driver, vehicle=bus).json()
    response = client.patch(
        f"/dispatch-tasks/{task['id']}",
        headers=admin_headers,
        json={"vehicle_id": None, "status": "completed"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["vehicle_id"] is None
    assert response.json()["status"] == "completed"
    assert (
        client.patch(
            f"/dispatch-tasks/{task['id']}", headers=admin_headers, json={"driver_id": None}
        ).status_code
        == 422
    )


def test_cancelling_is_audited_once_and_a_cancelled_task_is_frozen(
    client, admin_headers, db_session
):
    driver = _driver(client, admin_headers, "Pat")
    task = _task(client, admin_headers, driver).json()
    assert (
        client.post(f"/dispatch-tasks/{task['id']}/cancel", headers=admin_headers).status_code
        == 200
    )
    again = client.post(f"/dispatch-tasks/{task['id']}/cancel", headers=admin_headers)
    assert again.status_code == 409
    edit = client.patch(
        f"/dispatch-tasks/{task['id']}", headers=admin_headers, json={"instructions": "x"}
    )
    assert edit.status_code == 409
    assert len(_audits(db_session, task["id"], "cancelled")) == 1
    # Its time is free again.
    assert _task(client, admin_headers, driver).status_code == 201


def test_a_completed_task_cannot_be_cancelled(client, admin_headers, db_session):
    driver = _driver(client, admin_headers, "Pat")
    task = _task(client, admin_headers, driver).json()
    pat = _driver_login(client, db_session, driver, "pat@example.org")
    client.patch(f"/dispatch-tasks/{task['id']}/status", headers=pat, json={"status": "completed"})
    response = client.post(f"/dispatch-tasks/{task['id']}/cancel", headers=admin_headers)
    assert response.status_code == 409
    assert "already completed" in response.json()["detail"]


# --- The driver's side -------------------------------------------------------


def test_a_driver_sees_only_their_own_tasks_and_receipt_marks_them_received(
    client, admin_headers, db_session
):
    pat_driver = _driver(client, admin_headers, "Pat")
    sam_driver = _driver(client, admin_headers, "Sam")
    bus = _vehicle(client, admin_headers, "Bus 30")
    mine = _task(client, admin_headers, pat_driver, vehicle=bus).json()
    _task(client, admin_headers, sam_driver)
    pat = _driver_login(client, db_session, pat_driver, "pat@example.org")

    [listed] = client.get(f"/dispatch-tasks/mine/{DAY}", headers=pat).json()
    assert listed["id"] == mine["id"]
    assert listed["vehicle_label"] == "Bus 30"
    assert listed["instructions"].startswith("Bus 12 is down")
    assert "driver_full_name" not in listed

    first = client.post(f"/dispatch-tasks/mine/{DAY}/receipt", headers=pat)
    assert [t["status"] for t in first.json()] == ["received"]
    client.post(f"/dispatch-tasks/mine/{DAY}/receipt", headers=pat)
    assert len(_audits(db_session, mine["id"], "status_changed")) == 1


def test_a_driver_walks_a_task_forward_only(client, admin_headers, db_session):
    driver = _driver(client, admin_headers, "Pat")
    task = _task(client, admin_headers, driver).json()
    pat = _driver_login(client, db_session, driver, "pat@example.org")
    for target in ("acknowledged", "en_route", "arrived", "in_progress", "completed"):
        response = client.patch(
            f"/dispatch-tasks/{task['id']}/status", headers=pat, json={"status": target}
        )
        assert response.status_code == 200, (target, response.text)
        assert response.json()["status"] == target
    back = client.patch(
        f"/dispatch-tasks/{task['id']}/status", headers=pat, json={"status": "en_route"}
    )
    assert back.status_code == 409


def test_a_driver_cannot_touch_someone_elses_task(client, admin_headers, db_session):
    pat_driver = _driver(client, admin_headers, "Pat")
    sam_driver = _driver(client, admin_headers, "Sam")
    task = _task(client, admin_headers, pat_driver).json()
    sam = _driver_login(client, db_session, sam_driver, "sam@example.org")
    response = client.patch(
        f"/dispatch-tasks/{task['id']}/status", headers=sam, json={"status": "acknowledged"}
    )
    assert response.status_code == 403


def test_a_cancelled_task_stays_on_the_tablet_marked_cancelled(client, admin_headers, db_session):
    driver = _driver(client, admin_headers, "Pat")
    task = _task(client, admin_headers, driver).json()
    pat = _driver_login(client, db_session, driver, "pat@example.org")
    client.post(f"/dispatch-tasks/{task['id']}/cancel", headers=admin_headers)

    [listed] = client.get(f"/dispatch-tasks/mine/{DAY}", headers=pat).json()
    assert listed["cancelled"] is True
    # Receipt leaves it alone, and the driver can't move it.
    [after_receipt] = client.post(f"/dispatch-tasks/mine/{DAY}/receipt", headers=pat).json()
    assert after_receipt["status"] == "sent"
    response = client.patch(
        f"/dispatch-tasks/{task['id']}/status", headers=pat, json={"status": "acknowledged"}
    )
    assert response.status_code == 409
    assert "cancelled" in response.json()["detail"]


# --- Field trips on the driver's day -----------------------------------------


def test_the_assigned_driver_sees_their_field_trip_for_the_day(client, admin_headers, db_session):
    driver = _driver(client, admin_headers, "Pat")
    other = _driver(client, admin_headers, "Sam")
    bus = _vehicle(client, admin_headers, "Bus 30")
    profile = client.post(
        "/destination-profiles",
        headers=admin_headers,
        json={"name": "Science Museum", "approved_entrance": "North gate on Elm St"},
    ).json()
    trip = _trip(client, admin_headers, "09:00", "13:30")
    client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"destination_profile_id": profile["id"]},
    )
    assert _assign(client, admin_headers, trip, driver=driver, vehicle=bus).status_code == 200

    pat = _driver_login(client, db_session, driver, "pat@example.org")
    [mine] = client.get(f"/field-trips/mine/{DAY}", headers=pat).json()
    assert mine["id"] == trip["id"]
    assert mine["destination"] == "Science Museum"
    assert (mine["start_minute"], mine["end_minute"]) == (540, 810)  # unpadded 09:00-13:30
    assert mine["vehicle_label"] == "Bus 30"
    assert mine["destination_profile"]["approved_entrance"] == "North gate on Elm St"

    sam = _driver_login(client, db_session, other, "sam@example.org")
    assert client.get(f"/field-trips/mine/{DAY}", headers=sam).json() == []
    assert client.get("/field-trips/mine/2026-10-09", headers=pat).json() == []
    # The dispatcher-facing list stays off limits to drivers.
    assert client.get("/field-trips", headers=pat).status_code == 403


def test_an_overnight_trip_shows_on_each_day_it_covers(client, admin_headers, db_session):
    driver = _driver(client, admin_headers, "Pat")
    trip = _trip(client, admin_headers, "08:00", "18:00", back_day="2026-10-10")
    _assign(client, admin_headers, trip, driver=driver)
    pat = _driver_login(client, db_session, driver, "pat@example.org")
    [middle] = client.get("/field-trips/mine/2026-10-09", headers=pat).json()
    assert (middle["start_minute"], middle["end_minute"]) == (0, 1439)
    [last] = client.get("/field-trips/mine/2026-10-10", headers=pat).json()
    assert (last["start_minute"], last["end_minute"]) == (0, 1080)
