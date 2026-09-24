"""Driver and vehicle availability is a scheduling constraint (spec
sections 2.1, 5, 13): absences, out-of-service vehicles and deactivated
drivers are honored by the solver, manual overrides, crew creation,
template generation and substitute ranking alike."""

from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user

DAY = "2026-10-05"


def _school(client, h):
    return client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _crew(client, h, label, *, day=DAY, earliest=360, latest=1000):
    driver = client.post("/drivers", headers=h, json={"full_name": f"Driver {label}"}).json()
    vehicle = client.post("/vehicles", headers=h, json={"label": f"Bus {label}"}).json()
    crew = client.post(
        "/crews",
        headers=h,
        json={
            "service_date": day,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": earliest,
            "available_window_latest": latest,
        },
    )
    assert crew.status_code == 201, crew.text
    return driver, vehicle, crew.json()


def _run(client, h, school, earliest, latest, *, day=DAY, duration=30):
    response = client.post(
        "/runs",
        headers=h,
        json={
            "service_date": day,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": earliest,
            "window_latest": latest,
            "duration_minutes": duration,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _absent(client, h, driver, start=0, end=1439, *, day=DAY):
    response = client.post(
        f"/drivers/{driver['id']}/absences",
        headers=h,
        json={
            "service_date": day,
            "start_minute": start,
            "end_minute": end,
            "reason": "sick_leave",
        },
    )
    assert response.status_code == 201, response.text


def _solve(client, h, day=DAY):
    return client.post("/schedule", headers=h, json={"service_date": day})


def _crew_ids(response):
    return {a["crew_id"] for a in response.json()["assignments"]}


def _preferred_crew_scenario(client, h):
    """Crew A can cover both runs alone, so minimizing crews makes it the
    solver's unique best choice. B and C can each cover only one run.
    Once A is unavailable the only valid plan is B + C, so these tests
    can't pass by tie-break luck."""
    school = _school(client, h)
    a_driver, a_vehicle, a_crew = _crew(client, h, "A", earliest=360, latest=1000)
    _, _, b_crew = _crew(client, h, "B", earliest=360, latest=500)
    _, _, c_crew = _crew(client, h, "C", earliest=560, latest=700)
    _run(client, h, school, 400, 440)
    _run(client, h, school, 600, 640)
    assert _crew_ids(_solve(client, h)) == {a_crew["id"]}  # the baseline
    return a_driver, a_vehicle, {b_crew["id"], c_crew["id"]}


# --- The solver -------------------------------------------------------------


def test_absence_recorded_after_the_crew_exists_keeps_the_driver_off_the_schedule(
    client, admin_headers
):
    a_driver, _, fallback = _preferred_crew_scenario(client, admin_headers)
    _absent(client, admin_headers, a_driver)

    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert _crew_ids(response) == fallback


def test_only_crew_absent_makes_the_day_infeasible_and_says_why(client, admin_headers):
    school = _school(client, admin_headers)
    driver, _, _ = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 420, 480)
    _absent(client, admin_headers, driver)

    response = _solve(client, admin_headers)
    assert response.status_code == 422
    assert "No available crews" in response.json()["detail"]
    assert "driver absent (sick leave" in response.json()["detail"]


def test_partial_day_absence_only_blocks_the_minutes_it_covers(client, admin_headers):
    # One crew, absent 07:00-08:00: the 06:00 run fits before it, and a
    # run whose window lies entirely inside the absence can't be covered.
    school = _school(client, admin_headers)
    driver, _, crew = _crew(client, admin_headers, "A")
    early = _run(client, admin_headers, school, 360, 400)
    _absent(client, admin_headers, driver, 420, 480)

    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    [assignment] = response.json()["assignments"]
    assert assignment["run_id"] == early["id"] and assignment["crew_id"] == crew["id"]

    _run(client, admin_headers, school, 425, 475)
    assert _solve(client, admin_headers).status_code == 422


def test_out_of_service_vehicle_is_not_scheduled(client, admin_headers):
    _, a_vehicle, fallback = _preferred_crew_scenario(client, admin_headers)
    client.patch(f"/vehicles/{a_vehicle['id']}", headers=admin_headers, json={"is_active": False})

    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert _crew_ids(response) == fallback


def test_deactivated_driver_is_not_scheduled(client, admin_headers):
    a_driver, _, fallback = _preferred_crew_scenario(client, admin_headers)
    client.patch(f"/drivers/{a_driver['id']}", headers=admin_headers, json={"is_active": False})

    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert _crew_ids(response) == fallback


def test_locked_assignment_on_a_now_absent_crew_stays_but_is_flagged(client, admin_headers):
    school = _school(client, admin_headers)
    driver, _, crew = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 420, 480)
    [assignment] = _solve(client, admin_headers).json()["assignments"]
    assert assignment["availability_issue"] is None
    client.patch(
        f"/schedule/assignments/{assignment['id']}", headers=admin_headers, json={"locked": True}
    )
    _absent(client, admin_headers, driver)

    [kept] = _solve(client, admin_headers).json()["assignments"]
    assert kept["id"] == assignment["id"] and kept["crew_id"] == crew["id"]
    assert kept["availability_issue"].startswith("driver absent (sick leave")

    [listed] = client.get(f"/schedule/{DAY}/assignments", headers=admin_headers).json()
    assert listed["availability_issue"] == kept["availability_issue"]


def test_unaffected_assignments_have_no_availability_issue(client, admin_headers):
    school = _school(client, admin_headers)
    _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 420, 480)
    _solve(client, admin_headers)
    [listed] = client.get(f"/schedule/{DAY}/assignments", headers=admin_headers).json()
    assert listed["availability_issue"] is None


# --- Manual overrides and crews ----------------------------------------------


def test_manual_reassignment_onto_an_absent_driver_is_rejected(client, admin_headers):
    school = _school(client, admin_headers)
    absent, _, absent_crew = _crew(client, admin_headers, "A")
    _crew(client, admin_headers, "B")
    _absent(client, admin_headers, absent, 400, 500)
    _run(client, admin_headers, school, 420, 480)
    [assignment] = _solve(client, admin_headers).json()["assignments"]

    response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"crew_id": absent_crew["id"]},
    )
    assert response.status_code == 422
    assert "unavailable" in response.json()["detail"]


def test_crews_cannot_be_created_on_out_of_service_or_deactivated_resources(client, admin_headers):
    driver = client.post("/drivers", headers=admin_headers, json={"full_name": "D"}).json()
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": "Bus"}).json()
    body = {
        "service_date": DAY,
        "driver_id": driver["id"],
        "vehicle_id": vehicle["id"],
        "available_window_earliest": 360,
        "available_window_latest": 1000,
    }

    client.patch(f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"is_active": False})
    response = client.post("/crews", headers=admin_headers, json=body)
    assert response.status_code == 400
    assert "out of service" in response.json()["detail"]

    client.patch(f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"is_active": True})
    client.patch(f"/drivers/{driver['id']}", headers=admin_headers, json={"is_active": False})
    response = client.post("/crews", headers=admin_headers, json=body)
    assert response.status_code == 400
    assert "deactivated" in response.json()["detail"]


def test_repointing_a_crew_to_a_substitute_who_is_also_absent_is_rejected(client, admin_headers):
    school = _school(client, admin_headers)
    driver, _, crew = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 420, 480)
    _solve(client, admin_headers)
    substitute = client.post("/drivers", headers=admin_headers, json={"full_name": "Sub"}).json()
    _absent(client, admin_headers, substitute, 400, 500)

    response = client.patch(
        f"/crews/{crew['id']}", headers=admin_headers, json={"driver_id": substitute["id"]}
    )
    assert response.status_code == 409
    assert "driver absent" in response.json()["detail"]


# --- Substitutes and templates -----------------------------------------------


def test_substitute_ranking_leaves_out_absent_and_deactivated_drivers(client, admin_headers):
    school = _school(client, admin_headers)
    driver, _, _ = _crew(client, admin_headers, "A")
    _run(client, admin_headers, school, 420, 480)
    _solve(client, admin_headers)

    def driver_named(name):
        return client.post("/drivers", headers=admin_headers, json={"full_name": name}).json()

    free = driver_named("Free Sub")
    busy = driver_named("Absent Sub")
    gone = driver_named("Deactivated Sub")
    _absent(client, admin_headers, busy, 400, 500)
    client.patch(f"/drivers/{gone['id']}", headers=admin_headers, json={"is_active": False})

    [affected] = client.get(
        f"/drivers/{driver['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": DAY},
    ).json()
    names = {c["full_name"] for c in affected["candidates"]}
    assert "Free Sub" in names
    assert "Absent Sub" not in names and "Deactivated Sub" not in names
    assert free["id"] in {c["driver_id"] for c in affected["candidates"]}


def test_template_generation_skips_out_of_service_vehicles_and_reports_them(client, admin_headers):
    driver = client.post("/drivers", headers=admin_headers, json={"full_name": "D"}).json()
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": "Bus"}).json()
    template = client.post(
        "/crew-templates",
        headers=admin_headers,
        json={
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 360,
            "available_window_latest": 1000,
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
        },
    ).json()
    client.patch(f"/vehicles/{vehicle['id']}", headers=admin_headers, json={"is_active": False})

    result = client.post(f"/schedule/{DAY}/generate-from-templates", headers=admin_headers).json()
    assert result["crews_created"] == 0
    assert result["crews_skipped_out_of_service_template_ids"] == [template["id"]]
    assert client.get("/crews", headers=admin_headers, params={"service_date": DAY}).json() == []


def test_dispatchers_get_the_same_availability_rules(client, admin_headers, db_session):
    # RBAC unchanged: a dispatcher can still run the schedule, and the
    # availability rules apply regardless of who asks.
    a_driver, _, fallback = _preferred_crew_scenario(client, admin_headers)
    _absent(client, admin_headers, a_driver)
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="disp@example.org"))

    response = _solve(client, dispatcher)
    assert response.status_code == 200, response.text
    assert _crew_ids(response) == fallback
