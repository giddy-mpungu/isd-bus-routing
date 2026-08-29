"""Phase 6 first slice: driver absence reporting + substitute
candidate ranking (spec section 13)."""

from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user

SERVICE_DATE = "2026-09-01"


def _seed_driver_crew_and_run(
    client,
    admin_headers,
    *,
    label,
    school_id=None,
    window_earliest=360,
    window_latest=410,
    duration_minutes=40,
    buffer_minutes=10,
    max_continuous_minutes=None,
    qualification_code=None,
    service_date=SERVICE_DATE,
):
    """qualification_code, when given, gates both the vehicle and the
    run so this crew is the *only* one eligible for this run — without
    it, two same-school runs on the same day with non-overlapping
    windows leave the solver free to combine them onto one crew
    (minimize-crews-used), making which driver ends up "busy" a solver
    tie rather than a test fixture — the same class of flakiness this
    project's Phase 2 test suite already hit once (see docs/REBOOT.md).
    Forcing eligibility removes the ambiguity outright."""
    if school_id is None:
        school = client.post(
            "/schools",
            headers=admin_headers,
            json={"name": "Riverside Elementary", "location_lat": 29.7, "location_lon": -95.4},
        ).json()
        school_id = school["id"]
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"full_name": f"Driver {label}", "max_continuous_minutes": max_continuous_minutes},
    ).json()
    vehicle_payload = {"label": f"Bus {label}"}
    if qualification_code:
        client.post(
            "/qualifications",
            headers=admin_headers,
            json={"code": qualification_code, "kind": "vehicle_capability"},
        )
        vehicle_payload["qualification_codes"] = [qualification_code]
    vehicle = client.post("/vehicles", headers=admin_headers, json=vehicle_payload).json()
    crew = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    ).json()
    run_payload = {
        "service_date": service_date,
        "school_id": school_id,
        "window_earliest": window_earliest,
        "window_latest": window_latest,
        "duration_minutes": duration_minutes,
        "buffer_minutes": buffer_minutes,
    }
    if qualification_code:
        run_payload["required_qualification_codes"] = [qualification_code]
    run = client.post("/runs", headers=admin_headers, json=run_payload).json()
    return school_id, driver, vehicle, crew, run


def test_driver_can_report_own_absence(client, admin_headers, db_session):
    _school, driver, _vehicle, _crew, _run = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER, driver_id=driver["id"])
    token = login(client, email="driver1@example.org")

    response = client.post(
        f"/drivers/{driver['id']}/absences",
        headers=auth_headers(token),
        json={
            "service_date": SERVICE_DATE,
            "start_minute": 0,
            "end_minute": 1439,
            "reason": "sick_leave",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["reason"] == "sick_leave"


def test_driver_cannot_report_another_drivers_absence(client, admin_headers, db_session):
    _school, driver_a, _v1, _c1, _r1 = _seed_driver_crew_and_run(client, admin_headers, label="A")
    _school2, driver_b, _v2, _c2, _r2 = _seed_driver_crew_and_run(client, admin_headers, label="B")
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER, driver_id=driver_a["id"])
    token = login(client, email="driver1@example.org")

    response = client.post(
        f"/drivers/{driver_b['id']}/absences",
        headers=auth_headers(token),
        json={
            "service_date": SERVICE_DATE,
            "start_minute": 0,
            "end_minute": 1439,
            "reason": "sick_leave",
        },
    )
    assert response.status_code == 403


def test_dispatcher_can_report_absence_for_any_driver(client, admin_headers, db_session):
    _school, driver, _vehicle, _crew, _run = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    make_user(db_session, email="dispatcher5@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher5@example.org")

    response = client.post(
        f"/drivers/{driver['id']}/absences",
        headers=auth_headers(token),
        json={
            "service_date": SERVICE_DATE,
            "start_minute": 0,
            "end_minute": 1439,
            "reason": "no_call_no_show",
        },
    )
    assert response.status_code == 201


def test_listing_all_absences_for_a_date_spans_every_driver(client, admin_headers):
    _school, driver_a, _va, _ca, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    _school2, driver_b, _vb, _cb, _run_b = _seed_driver_crew_and_run(
        client, admin_headers, label="B"
    )
    client.post(
        f"/drivers/{driver_a['id']}/absences",
        headers=admin_headers,
        json={
            "service_date": SERVICE_DATE,
            "start_minute": 0,
            "end_minute": 1439,
            "reason": "sick_leave",
        },
    )
    client.post(
        f"/drivers/{driver_b['id']}/absences",
        headers=admin_headers,
        json={
            "service_date": SERVICE_DATE,
            "start_minute": 0,
            "end_minute": 1439,
            "reason": "training",
        },
    )

    response = client.get("/absences", headers=admin_headers, params={"service_date": SERVICE_DATE})
    assert response.status_code == 200
    driver_ids = {a["driver_id"] for a in response.json()}
    assert driver_ids == {driver_a["id"], driver_b["id"]}


def test_listing_all_absences_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    _school, driver, _vehicle, _crew, _run = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER, driver_id=driver["id"])
    token = login(client, email="driver1@example.org")

    response = client.get(
        "/absences", headers=auth_headers(token), params={"service_date": SERVICE_DATE}
    )
    assert response.status_code == 403


def test_listing_absences_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    _school, driver, _vehicle, _crew, _run = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER, driver_id=driver["id"])
    token = login(client, email="driver1@example.org")

    response = client.get(
        f"/drivers/{driver['id']}/absences",
        headers=auth_headers(token),
        params={"service_date": SERVICE_DATE},
    )
    assert response.status_code == 403


def test_substitute_candidates_empty_when_no_crew_that_date(client, admin_headers):
    driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Unscheduled Driver"}
    ).json()
    response = client.get(
        f"/drivers/{driver['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": SERVICE_DATE},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_substitute_candidates_returns_affected_assignment_and_freed_vehicle(client, admin_headers):
    school_id, driver_a, vehicle_a, _crew_a, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    response = client.get(
        f"/drivers/{driver_a['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": SERVICE_DATE},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["vehicle_id"] == vehicle_a["id"]
    assert body[0]["vehicle_label"] == vehicle_a["label"]
    assert body[0]["school_name"] == "Riverside Elementary"


def test_substitute_candidates_excludes_the_absent_driver_themself(client, admin_headers):
    school_id, driver_a, _va, _ca, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    _seed_driver_crew_and_run(client, admin_headers, label="B", school_id=school_id)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    response = client.get(
        f"/drivers/{driver_a['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": SERVICE_DATE},
    )
    candidate_ids = {c["driver_id"] for c in response.json()[0]["candidates"]}
    assert driver_a["id"] not in candidate_ids


def test_substitute_candidates_excludes_a_double_booked_driver(client, admin_headers):
    school_id, driver_a, _va, _ca, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A", window_earliest=360, window_latest=410
    )
    # Two crews, two runs whose windows genuinely overlap — the only
    # feasible solve uses both crews (one each), so which crew serves
    # which run doesn't matter: driver_a and driver_b end up with
    # overlapping-time assignments either way, and must exclude each
    # other regardless of the specific pairing the solver picks.
    _school2, driver_b, _vb, _cb, _run_b = _seed_driver_crew_and_run(
        client,
        admin_headers,
        label="B",
        school_id=school_id,
        window_earliest=370,
        window_latest=420,
    )
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    response = client.get(
        f"/drivers/{driver_a['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": SERVICE_DATE},
    )
    candidate_ids = {c["driver_id"] for c in response.json()[0]["candidates"]}
    assert driver_b["id"] not in candidate_ids


def test_substitute_candidates_excludes_a_driver_over_duty_limit(client, admin_headers):
    school_id, driver_a, _va, _ca, _run_a = _seed_driver_crew_and_run(
        client,
        admin_headers,
        label="A",
        window_earliest=360,
        window_latest=410,
        duration_minutes=40,
        qualification_code="qual-a",
    )
    # Driver B has a non-overlapping run that day using 30 minutes of
    # duty (qualification-forced onto crew_b specifically, so the
    # solver can't dodge using it), and a 50-minute continuous-duty
    # cap — adding driver A's 40-minute affected run would exceed it.
    _school2, driver_b, _vb, _cb, _run_b = _seed_driver_crew_and_run(
        client,
        admin_headers,
        label="B",
        school_id=school_id,
        window_earliest=480,
        window_latest=510,
        duration_minutes=30,
        buffer_minutes=0,
        max_continuous_minutes=50,
        qualification_code="qual-b",
    )
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    response = client.get(
        f"/drivers/{driver_a['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": SERVICE_DATE},
    )
    candidate_ids = {c["driver_id"] for c in response.json()[0]["candidates"]}
    assert driver_b["id"] not in candidate_ids


def test_substitute_candidates_ranks_school_familiarity_higher(client, admin_headers):
    school_id, driver_a, _va, _ca, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A", qualification_code="qual-a"
    )
    # Driver C has prior history at this school (an earlier-date
    # assignment) but no crew/run today at all; driver D has neither —
    # nothing for today's solve to entangle, isolating the comparison
    # to familiarity alone.
    driver_c = client.post("/drivers", headers=admin_headers, json={"full_name": "Driver C"}).json()
    vehicle_c = client.post("/vehicles", headers=admin_headers, json={"label": "Bus C"}).json()
    driver_d = client.post("/drivers", headers=admin_headers, json={"full_name": "Driver D"}).json()

    earlier_date = "2026-08-25"
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": earlier_date,
            "driver_id": driver_c["id"],
            "vehicle_id": vehicle_c["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    )
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": earlier_date,
            "school_id": school_id,
            "window_earliest": 360,
            "window_latest": 410,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    )
    prior_schedule = client.post(
        "/schedule", headers=admin_headers, json={"service_date": earlier_date}
    )
    assert prior_schedule.status_code == 200, prior_schedule.text

    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    response = client.get(
        f"/drivers/{driver_a['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": SERVICE_DATE},
    )
    candidates = response.json()[0]["candidates"]
    ranks = {c["driver_id"]: i for i, c in enumerate(candidates)}
    assert ranks[driver_c["id"]] < ranks[driver_d["id"]]


def test_substitute_candidates_ranks_lower_same_day_workload_higher(client, admin_headers):
    school_id, driver_a, _va, _ca, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A", qualification_code="qual-a"
    )
    # Driver E has a second, non-overlapping, qualification-forced run
    # the same day (so the solver can't leave crew_e unused) — at a
    # *different* school, so it doesn't also inflate E's familiarity
    # score for driver_a's school and confound the comparison. Busier
    # than driver F, who has no crew/run today at all.
    _s2, driver_e, _ve, _ce, _run_e = _seed_driver_crew_and_run(
        client,
        admin_headers,
        label="E",
        window_earliest=600,
        window_latest=650,
        qualification_code="qual-e",
    )
    driver_f = client.post("/drivers", headers=admin_headers, json={"full_name": "Driver F"}).json()

    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    response = client.get(
        f"/drivers/{driver_a['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": SERVICE_DATE},
    )
    candidates = response.json()[0]["candidates"]
    ranks = {c["driver_id"]: i for i, c in enumerate(candidates)}
    assert ranks[driver_f["id"]] < ranks[driver_e["id"]]


def test_substitute_candidates_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    _school, driver_a, _va, _ca, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER, driver_id=driver_a["id"])
    token = login(client, email="driver1@example.org")

    response = client.get(
        f"/drivers/{driver_a['id']}/substitute-candidates",
        headers=auth_headers(token),
        params={"service_date": SERVICE_DATE},
    )
    assert response.status_code == 403


def test_substitute_candidates_response_includes_the_crew_id(client, admin_headers):
    """The crew id is what a caller actually needs to complete a
    substitution via PATCH /crews/{id} when the candidate has no crew
    of their own that date — see that endpoint's docstring for why."""
    school_id, driver_a, _va, crew_a, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": SERVICE_DATE})
    assert schedule.status_code == 200, schedule.text

    response = client.get(
        f"/drivers/{driver_a['id']}/substitute-candidates",
        headers=admin_headers,
        params={"service_date": SERVICE_DATE},
    )
    assert response.json()[0]["crew_id"] == crew_a["id"]


def test_update_crew_driver_repoints_it(client, admin_headers):
    """spec section 13.2: a vehicle already claimed by a crew row for a
    date can't be paired with a second driver via POST /crews (its own
    uniqueness constraint rejects that) — repointing the existing
    crew's driver is how a candidate with no crew of their own that
    date gets substituted in."""
    _school, _driver_a, _va, crew_a, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    substitute = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Substitute Driver"}
    ).json()

    response = client.patch(
        f"/crews/{crew_a['id']}", headers=admin_headers, json={"driver_id": substitute["id"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["driver_id"] == substitute["id"]
    assert response.json()["vehicle_id"] == crew_a["vehicle_id"]


def test_update_crew_driver_conflicts_if_new_driver_already_has_a_crew_that_date(
    client, admin_headers
):
    _school, _driver_a, _va, crew_a, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    _school2, driver_b, _vb, _cb, _run_b = _seed_driver_crew_and_run(
        client, admin_headers, label="B"
    )

    response = client.patch(
        f"/crews/{crew_a['id']}", headers=admin_headers, json={"driver_id": driver_b["id"]}
    )
    assert response.status_code == 409


def test_update_crew_driver_rejects_unknown_driver_id(client, admin_headers):
    _school, _driver_a, _va, crew_a, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    response = client.patch(
        f"/crews/{crew_a['id']}", headers=admin_headers, json={"driver_id": 999999}
    )
    assert response.status_code == 400


def test_update_crew_driver_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    _school, driver_a, _va, crew_a, _run_a = _seed_driver_crew_and_run(
        client, admin_headers, label="A"
    )
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER, driver_id=driver_a["id"])
    token = login(client, email="driver1@example.org")

    response = client.patch(
        f"/crews/{crew_a['id']}", headers=auth_headers(token), json={"driver_id": driver_a["id"]}
    )
    assert response.status_code == 403
