"""Spec section 16: "a mathematically feasible schedule should be
rejected or flagged if it lacks sufficient operational buffer". The
district's minimum buffer between consecutive runs is a hard constraint
on the solver and on manual reassignment."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

DAY = "2026-10-05"


def _settings(client, h, minimum, **weights):
    return client.put(
        "/optimization-settings",
        headers=h,
        json={
            "crews_used_weight": weights.get("crews", 1),
            "deadhead_minutes_weight": 0,
            "arrival_buffer_weight": 0,
            "minimum_buffer_minutes": minimum,
        },
    )


def _seed(client, h, *, crews=2):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    made = []
    for label in "AB"[:crews]:
        driver = client.post("/drivers", headers=h, json={"full_name": f"Driver {label}"}).json()
        vehicle = client.post("/vehicles", headers=h, json={"label": f"Bus {label}"}).json()
        made.append(
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
            ).json()
        )
    # Same school, so no travel between them. Chained on one crew, the
    # most spare time possible is 470 - 430 = 40 minutes.
    runs = [
        client.post(
            "/runs",
            headers=h,
            json={
                "service_date": DAY,
                "school_id": school["id"],
                "direction": "am",
                "window_earliest": earliest,
                "window_latest": latest,
                "duration_minutes": 30,
            },
        ).json()
        for earliest, latest in ((400, 440), (450, 500))
    ]
    return made, runs


def _solve(client, h):
    return client.post("/schedule", headers=h, json={"service_date": DAY})


def test_the_minimum_buffer_is_saved_audited_and_validated(client, admin_headers, db_session):
    response = _settings(client, admin_headers, 15)
    assert response.status_code == 200, response.text
    assert response.json()["minimum_buffer_minutes"] == 15
    assert (
        client.get("/optimization-settings", headers=admin_headers).json()["minimum_buffer_minutes"]
        == 15
    )
    entry = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "optimization_settings")
        .one()
    )
    assert entry.after_state["minimum_buffer_minutes"] == 15

    for bad in (-1, 121):
        assert _settings(client, admin_headers, bad).status_code == 422


def test_older_clients_that_omit_the_field_get_no_minimum(client, admin_headers):
    response = client.put(
        "/optimization-settings",
        headers=admin_headers,
        json={"crews_used_weight": 1, "deadhead_minutes_weight": 0, "arrival_buffer_weight": 0},
    )
    assert response.status_code == 200
    assert response.json()["minimum_buffer_minutes"] == 0


def test_only_a_transportation_admin_sets_it(client, admin_headers, db_session):
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="disp@example.org"))
    assert _settings(client, dispatcher, 15).status_code == 403


def test_without_a_minimum_the_runs_chain_on_one_crew(client, admin_headers):
    _seed(client, admin_headers)
    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["crews_used"] == 1


def test_a_minimum_the_chain_cannot_meet_uses_a_second_crew(client, admin_headers):
    _seed(client, admin_headers)
    _settings(client, admin_headers, 45)
    response = _solve(client, admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["crews_used"] == 2


def test_a_minimum_no_plan_can_meet_is_rejected_and_says_why(client, admin_headers):
    _seed(client, admin_headers, crews=1)
    _settings(client, admin_headers, 45)
    response = _solve(client, admin_headers)
    assert response.status_code == 422
    assert "minimum buffer of 45 minutes" in response.json()["detail"]


def test_a_minimum_the_chain_can_meet_is_reported_in_the_explanation(client, admin_headers):
    _seed(client, admin_headers)
    _settings(client, admin_headers, 40)
    body = _solve(client, admin_headers).json()
    assert body["crews_used"] == 1
    first = min(body["assignments"], key=lambda a: a["start_minute"])
    assert "at least 40 minutes of operational buffer" in first["explanation_text"]


def test_manual_reassignment_that_breaks_the_minimum_is_rejected(client, admin_headers):
    (crew_a, crew_b), _ = _seed(client, admin_headers)
    _settings(client, admin_headers, 45)
    assignments = _solve(client, admin_headers).json()["assignments"]
    first, second = sorted(assignments, key=lambda a: a["start_minute"])
    target = first["crew_id"]

    response = client.patch(
        f"/schedule/assignments/{second['id']}",
        headers=admin_headers,
        json={"crew_id": target},
    )
    assert response.status_code == 422
    assert "minimum buffer of 45 minutes" in response.json()["detail"]
