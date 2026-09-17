"""Reproduces the spec section 5 worked example end-to-end: persist a
school/vehicle/driver/crew/three runs via the API, call POST /schedule
as a dispatcher, and verify the solver's result was correctly persisted
as Assignments, is readable with correct RBAC scoping, and produced
audit trail entries.

Also covers the spec section 21 human-override endpoints (PATCH/DELETE
on a single assignment) and lock-aware re-scheduling.
"""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _add_crew(
    client,
    admin_headers,
    *,
    label,
    vehicle_qualification_codes=None,
    capacity=48,
    service_date="2026-09-01",
):
    """A second driver+vehicle+crew, available all day, for the same
    service_date — used by tests that need two crews to choose between.
    vehicle_qualification_codes must already exist (POST /qualifications)."""
    driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": f"Driver {label}"}
    ).json()
    vehicle = client.post(
        "/vehicles",
        headers=admin_headers,
        json={
            "label": f"Bus {label}",
            "nominal_capacity": capacity,
            "effective_capacity": capacity,
            "qualification_codes": vehicle_qualification_codes or [],
        },
    ).json()
    return client.post(
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


def _seed_spec_section5_scenario(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Multi-level campus", "location_lat": 29.70, "location_lon": -95.40},
    ).json()

    client.post("/qualifications", headers=admin_headers, json={"code": "CDL_B", "kind": "license"})
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"full_name": "Jordan Driver", "qualification_codes": ["CDL_B"]},
    ).json()
    vehicle = client.post(
        "/vehicles",
        headers=admin_headers,
        json={"label": "Bus 101", "nominal_capacity": 48, "effective_capacity": 44},
    ).json()
    crew = client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    ).json()

    run_specs = [
        (360, 410, 40, 10, 12),  # Pre-K 6:00-6:50
        (420, 470, 40, 10, 35),  # HS 7:00-7:50
        (480, 540, 45, 15, 28),  # MS 8:00-9:00
    ]
    runs = []
    for earliest, latest, duration, buffer_, passengers in run_specs:
        run = client.post(
            "/runs",
            headers=admin_headers,
            json={
                "service_date": "2026-09-01",
                "school_id": school["id"],
                "direction": "am",
                "window_earliest": earliest,
                "window_latest": latest,
                "duration_minutes": duration,
                "buffer_minutes": buffer_,
                "passenger_count": passengers,
            },
        ).json()
        runs.append(run)

    return school, driver, vehicle, crew, runs


def test_full_schedule_flow_persists_assignments_with_explanations(
    client, admin_headers, db_session
):
    _school, _driver, _vehicle, crew, runs = _seed_spec_section5_scenario(client, admin_headers)

    response = client.post(
        "/schedule",
        headers=admin_headers,
        json={"service_date": "2026-09-01", "average_deadhead_speed_kmh": 40.0},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["crews_used"] == 1
    assert len(body["assignments"]) == 3
    for assignment in body["assignments"]:
        assert assignment["crew_id"] == crew["id"]
        assert "qualifications" in assignment["explanation_text"]

    # Persisted, not just returned: fetch again via the read endpoint.
    read_back = client.get("/schedule/2026-09-01/assignments", headers=admin_headers)
    assert read_back.status_code == 200
    assert {a["run_id"] for a in read_back.json()} == {r["id"] for r in runs}


def test_schedule_uses_ors_estimator_when_api_key_configured(client, admin_headers, monkeypatch):
    """Config-gated wiring (Phase 6 GIS slice 1): when ISD_API_ORS_API_KEY
    is set, POST /schedule must build its estimator via
    isd_solver.ors_deadhead_estimator, not the Phase 1 straight-line
    approximation. No live ORS call is made — the estimator factory
    itself is replaced with a fake that returns a fixed estimate, since
    this sandbox has no network access to a real routing API (see
    isd_solver.domain.ors_deadhead_estimator's own docstring)."""
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)

    import isd_api.routers.schedule as schedule_module

    monkeypatch.setattr(schedule_module.settings, "ors_api_key", "test-key")
    calls = []

    def fake_ors_deadhead_estimator(**kwargs):
        calls.append(kwargs)
        return lambda a, b, v: 5

    monkeypatch.setattr(schedule_module, "ors_deadhead_estimator", fake_ors_deadhead_estimator)

    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert calls[0]["api_key"] == "test-key"
    assert calls[0]["profile"] == "driving-hgv"
    assert "fallback" in calls[0]


def test_schedule_passes_vehicle_dimensions_through_to_the_deadhead_estimator(
    client, admin_headers, monkeypatch
):
    """Phase 6 spec section 6 wiring: a vehicle's persisted length_m/
    width_m/height_m/weight_kg must reach the estimator call inside
    scheduler.py's pairwise-ordering loop, not just _to_solver_inputs
    — the exact "three places" gotcha (REBOOT.md #7) this PR fixes at
    the SolverVehicle(...) constructor call. Two runs are needed (not
    _seed_single_run_scenario's one) so the pairwise loop that actually
    invokes deadhead_estimator is exercised at all."""
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "S", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    driver = client.post("/drivers", headers=admin_headers, json={"full_name": "D"}).json()
    vehicle = client.post(
        "/vehicles",
        headers=admin_headers,
        json={
            "label": "Big Bus",
            "length_m": 10.5,
            "width_m": 2.5,
            "height_m": 3.2,
            "weight_kg": 12000.0,
        },
    ).json()
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    )
    for earliest, latest in [(360, 410), (420, 470)]:
        client.post(
            "/runs",
            headers=admin_headers,
            json={
                "service_date": "2026-09-01",
                "school_id": school["id"],
                "direction": "am",
                "window_earliest": earliest,
                "window_latest": latest,
                "duration_minutes": 40,
                "buffer_minutes": 10,
            },
        )

    import isd_api.routers.schedule as schedule_module

    monkeypatch.setattr(schedule_module.settings, "ors_api_key", "test-key")
    seen_vehicles = []

    def fake_ors_deadhead_estimator(**kwargs):
        def estimate(a, b, vehicle):
            seen_vehicles.append(vehicle)
            return 5

        return estimate

    monkeypatch.setattr(schedule_module, "ors_deadhead_estimator", fake_ors_deadhead_estimator)

    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text
    assert seen_vehicles  # the pairwise loop actually called the estimator
    for solver_vehicle in seen_vehicles:
        assert solver_vehicle.length_m == 10.5
        assert solver_vehicle.width_m == 2.5
        assert solver_vehicle.height_m == 3.2
        assert solver_vehicle.weight_kg == 12000.0


def test_schedule_ors_estimator_gets_avoid_polygons_for_hard_avoid_categories_only(
    client, admin_headers, monkeypatch
):
    """Phase 6 spec section 8 wiring: only GeographicKnowledgeOverride rows
    whose category is a hard-avoid one (frequent_flooding, unsafe_turn,
    invalid_turnaround) should end up in the ORS avoid_polygons geometry
    — a preferred_entrance override (a positive preference, the opposite
    of an avoidance) must not."""
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.70,
            "location_lon": -95.40,
            "category": "frequent_flooding",
            "note": "Floods after heavy rain.",
        },
    )
    client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.80,
            "location_lon": -95.50,
            "category": "preferred_entrance",
            "note": "Use the north gate for field trips.",
        },
    )

    import isd_api.routers.schedule as schedule_module

    monkeypatch.setattr(schedule_module.settings, "ors_api_key", "test-key")
    calls = []

    def fake_ors_deadhead_estimator(**kwargs):
        calls.append(kwargs)
        return lambda a, b, v: 5

    monkeypatch.setattr(schedule_module, "ors_deadhead_estimator", fake_ors_deadhead_estimator)

    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text

    avoid_polygons = calls[0]["avoid_polygons"]
    assert avoid_polygons["type"] == "MultiPolygon"
    assert len(avoid_polygons["coordinates"]) == 1  # only the flooding override, not the entrance
    ring = avoid_polygons["coordinates"][0][0]
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    assert min(lons) < -95.40 < max(lons)
    assert min(lats) < 29.70 < max(lats)


def test_schedule_applies_a_congestion_window_that_overlaps_todays_run(
    client, admin_headers, monkeypatch
):
    """Spec section 8: CONGESTION_WINDOW is applied per-solve when ANY
    job being scheduled today has a required window overlapping it —
    _seed_single_run_scenario's run has window [360, 420] (6:00-7:00am),
    so a congestion window of [400, 460] (6:40-7:40am) genuinely
    overlaps and must be included in the avoid geometry."""
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.70,
            "location_lon": -95.40,
            "category": "congestion_window",
            "note": "Backs up during morning drop-off.",
            "window_start_minute": 400,
            "window_end_minute": 460,
        },
    )

    import isd_api.routers.schedule as schedule_module

    monkeypatch.setattr(schedule_module.settings, "ors_api_key", "test-key")
    calls = []

    def fake_ors_deadhead_estimator(**kwargs):
        calls.append(kwargs)
        return lambda a, b, v: 5

    monkeypatch.setattr(schedule_module, "ors_deadhead_estimator", fake_ors_deadhead_estimator)

    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text

    avoid_polygons = calls[0]["avoid_polygons"]
    assert avoid_polygons is not None
    assert len(avoid_polygons["coordinates"]) == 1


def test_schedule_skips_a_congestion_window_that_does_not_overlap_any_run_today(
    client, admin_headers, monkeypatch
):
    """The same congestion override as above, but shifted so its time
    range no longer overlaps the run's [360, 420] window at all --
    it must be left out of the avoid geometry entirely."""
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.70,
            "location_lon": -95.40,
            "category": "congestion_window",
            "note": "Backs up during afternoon dismissal.",
            "window_start_minute": 900,
            "window_end_minute": 960,
        },
    )

    import isd_api.routers.schedule as schedule_module

    monkeypatch.setattr(schedule_module.settings, "ors_api_key", "test-key")
    calls = []

    def fake_ors_deadhead_estimator(**kwargs):
        calls.append(kwargs)
        return lambda a, b, v: 5

    monkeypatch.setattr(schedule_module, "ors_deadhead_estimator", fake_ors_deadhead_estimator)

    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text

    assert calls[0]["avoid_polygons"] is None


def test_schedule_passes_vehicle_size_restrictions_through_to_the_deadhead_estimator(
    client, admin_headers, monkeypatch
):
    """Spec section 8: VEHICLE_SIZE_RESTRICTED overrides reach the
    estimator as SizeRestriction objects, re-evaluated per vehicle --
    this test only checks the wiring (that schedule.py builds and
    passes them through correctly); isd_solver's own
    test_ors_deadhead_estimator.py covers the per-vehicle avoid-zone
    behavior itself."""
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    client.post(
        "/geographic-knowledge",
        headers=admin_headers,
        json={
            "location_lat": 29.75,
            "location_lon": -95.45,
            "category": "vehicle_size_restricted",
            "note": "Covered bridge on Elm St has a 3.0m height limit.",
            "restricted_dimension": "height_m",
            "max_allowed_value": 3.0,
        },
    )

    import isd_api.routers.schedule as schedule_module

    monkeypatch.setattr(schedule_module.settings, "ors_api_key", "test-key")
    calls = []

    def fake_ors_deadhead_estimator(**kwargs):
        calls.append(kwargs)
        return lambda a, b, v: 5

    monkeypatch.setattr(schedule_module, "ors_deadhead_estimator", fake_ors_deadhead_estimator)

    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text

    size_restrictions = calls[0]["size_restrictions"]
    assert len(size_restrictions) == 1
    assert size_restrictions[0].dimension == "height_m"
    assert size_restrictions[0].max_allowed == 3.0
    assert size_restrictions[0].location.lat == 29.75
    assert size_restrictions[0].location.lon == -95.45


def test_schedule_uses_straight_line_estimator_when_no_ors_key_configured(
    client, admin_headers, monkeypatch
):
    """Default/CI/local-dev config (no ORS key set) must not attempt to
    call isd_solver.ors_deadhead_estimator at all."""
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)

    import isd_api.routers.schedule as schedule_module

    assert schedule_module.settings.ors_api_key is None  # the default

    calls = []
    monkeypatch.setattr(
        schedule_module,
        "ors_deadhead_estimator",
        lambda **kwargs: calls.append(kwargs) or (lambda a, b, v: 5),
    )

    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text
    assert calls == []


def test_schedule_endpoint_requires_dispatcher_or_admin_role(client, db_session, admin_headers):
    _seed_spec_section5_scenario(client, admin_headers)
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.post(
        "/schedule", headers=auth_headers(token), json={"service_date": "2026-09-01"}
    )
    assert response.status_code == 403


def test_schedule_endpoint_reports_infeasible_clearly(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "S", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    driver = client.post("/drivers", headers=admin_headers, json={"full_name": "D"}).json()
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": "V"}).json()
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    )
    # A run requiring a qualification no crew has.
    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": "lift", "kind": "vehicle_capability"},
    )
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 420,
            "duration_minutes": 40,
            "buffer_minutes": 10,
            "required_qualification_codes": ["lift"],
        },
    )
    response = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert response.status_code == 422
    assert "qualified" in response.json()["detail"].lower()


def test_driver_only_sees_own_crews_assignments(client, admin_headers, db_session):
    _school, driver, _vehicle, crew, runs = _seed_spec_section5_scenario(client, admin_headers)
    client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})

    # This driver's User account is linked to the Driver record used above.
    make_user(db_session, email="driver1@example.org", role=Role.DRIVER, driver_id=driver["id"])
    token = login(client, email="driver1@example.org")
    response = client.get("/schedule/2026-09-01/assignments", headers=auth_headers(token))
    assert response.status_code == 200
    assert len(response.json()) == 3  # all three runs, all on this driver's crew

    # A second, unrelated driver sees nothing for this date.
    make_user(db_session, email="driver2@example.org", role=Role.DRIVER)
    other_driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Other Driver"}
    ).json()
    from isd_api.models import User

    unrelated = db_session.query(User).filter(User.email == "driver2@example.org").one()
    unrelated.driver_id = other_driver["id"]
    db_session.commit()
    token2 = login(client, email="driver2@example.org")
    response2 = client.get("/schedule/2026-09-01/assignments", headers=auth_headers(token2))
    assert response2.status_code == 200
    assert response2.json() == []


def test_rescheduling_replaces_prior_assignments_and_audits_both(client, admin_headers, db_session):
    _seed_spec_section5_scenario(client, admin_headers)
    first = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert first.status_code == 200

    second = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert second.status_code == 200

    # Exactly one current assignment per run — re-scheduling must not
    # leave stale rows behind (note: we don't assert new row IDs differ
    # from the first run's, since PostgreSQL sequences never reuse a
    # deleted ID but SQLite's rowid allocator can — that's a storage
    # detail, not a behavior this API promises).
    current = client.get("/schedule/2026-09-01/assignments", headers=admin_headers).json()
    assert len(current) == 3
    assert len({a["run_id"] for a in current}) == 3

    entries = (
        db_session.query(AuditLogEntry).filter(AuditLogEntry.entity_type == "assignment").all()
    )
    actions = [e.action for e in entries]
    assert actions.count("created") == 6  # 3 from first run + 3 from second
    assert actions.count("deleted") == 3  # the first run's assignments, replaced by the second
    assert all(e.actor_user_id is not None for e in entries)


def _seed_single_run_scenario(
    client,
    admin_headers,
    *,
    required_qualification_codes=None,
    passenger_count=0,
    service_date="2026-09-01",
):
    """One school, one run, one qualified/capacity-sufficient crew — the
    minimal scenario for testing a single PATCH/DELETE in isolation."""
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "S", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    for code in required_qualification_codes or []:
        client.post(
            "/qualifications",
            headers=admin_headers,
            json={"code": code, "kind": "vehicle_capability"},
        )
    crew = _add_crew(
        client,
        admin_headers,
        label="A",
        vehicle_qualification_codes=required_qualification_codes,
        capacity=48,
        service_date=service_date,
    )
    run = client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 420,
            "duration_minutes": 40,
            "buffer_minutes": 10,
            "passenger_count": passenger_count,
            "required_qualification_codes": required_qualification_codes or [],
        },
    ).json()
    return school, crew, run


def test_patch_assignment_reassigns_to_qualified_crew_and_audits(client, admin_headers, db_session):
    _school, crew1, _run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment = schedule.json()["assignments"][0]
    assert assignment["crew_id"] == crew1["id"]

    crew2 = _add_crew(client, admin_headers, label="B")
    response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"crew_id": crew2["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["crew_id"] == crew2["id"]
    # The stale solver-generated explanation (naming crew1) must not
    # survive a manual reassignment — it would misattribute the decision.
    assert f"Crew {crew2['id']} was manually assigned" in body["explanation_text"]
    assert f"Crew {crew1['id']} was assigned" not in body["explanation_text"]
    assert "admin" in body["explanation_text"]  # admin_headers' full_name, from make_user

    entries = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "assignment", AuditLogEntry.action == "updated")
        .all()
    )
    assert len(entries) == 1
    assert entries[0].before_state["crew_id"] == crew1["id"]
    assert entries[0].after_state["crew_id"] == crew2["id"]
    assert entries[0].actor_user_id is not None


def test_patch_assignment_rejects_unqualified_crew(client, admin_headers):
    _school, _crew1, _run = _seed_single_run_scenario(
        client, admin_headers, required_qualification_codes=["lift"]
    )
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment = schedule.json()["assignments"][0]

    unqualified_crew = _add_crew(client, admin_headers, label="B")  # no "lift"
    response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"crew_id": unqualified_crew["id"]},
    )
    assert response.status_code == 422
    assert "qualification" in response.json()["detail"].lower()


def test_patch_assignment_rejects_insufficient_capacity(client, admin_headers):
    _school, _crew1, _run = _seed_single_run_scenario(client, admin_headers, passenger_count=40)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment = schedule.json()["assignments"][0]

    small_crew = _add_crew(client, admin_headers, label="B", capacity=10)
    response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"crew_id": small_crew["id"]},
    )
    assert response.status_code == 422
    assert "capacity" in response.json()["detail"].lower()


def test_patch_assignment_rejects_overlapping_crew_assignment(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "S", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    # Both windows are exactly duration+buffer wide (no slack), so each
    # run occupies exactly its window — [360,410] and [380,430] overlap
    # unconditionally, forcing the solver to use two separate crews.
    run_a = client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 410,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    ).json()
    run_b = client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 380,
            "window_latest": 430,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    ).json()
    _add_crew(client, admin_headers, label="A")
    _add_crew(client, admin_headers, label="B")

    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert schedule.status_code == 200, schedule.text
    assignments = schedule.json()["assignments"]
    assert len(assignments) == 2
    by_run = {a["run_id"]: a for a in assignments}
    assert len({a["crew_id"] for a in assignments}) == 2

    a_assignment = by_run[run_a["id"]]
    b_assignment = by_run[run_b["id"]]
    response = client.patch(
        f"/schedule/assignments/{b_assignment['id']}",
        headers=admin_headers,
        json={"crew_id": a_assignment["crew_id"]},
    )
    assert response.status_code == 422
    assert "overlap" in response.json()["detail"].lower()


def test_patch_assignment_can_lock_and_unlock(client, admin_headers):
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment = schedule.json()["assignments"][0]
    assert assignment["locked"] is False

    locked = client.patch(
        f"/schedule/assignments/{assignment['id']}", headers=admin_headers, json={"locked": True}
    )
    assert locked.status_code == 200
    assert locked.json()["locked"] is True

    unlocked = client.patch(
        f"/schedule/assignments/{assignment['id']}", headers=admin_headers, json={"locked": False}
    )
    assert unlocked.status_code == 200
    assert unlocked.json()["locked"] is False


def test_patch_assignment_requires_dispatcher_or_admin_role(client, admin_headers, db_session):
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment = schedule.json()["assignments"][0]

    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=auth_headers(token),
        json={"locked": True},
    )
    assert response.status_code == 403


def test_delete_assignment_requires_dispatcher_or_admin_role(client, admin_headers, db_session):
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment = schedule.json()["assignments"][0]

    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.delete(
        f"/schedule/assignments/{assignment['id']}", headers=auth_headers(token)
    )
    assert response.status_code == 403


def test_delete_assignment_removes_it_and_audits(client, admin_headers, db_session):
    _school, _crew, _run = _seed_single_run_scenario(client, admin_headers)
    schedule = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignment = schedule.json()["assignments"][0]

    response = client.delete(f"/schedule/assignments/{assignment['id']}", headers=admin_headers)
    assert response.status_code == 204

    remaining = client.get("/schedule/2026-09-01/assignments", headers=admin_headers).json()
    assert remaining == []

    entries = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "assignment",
            AuditLogEntry.entity_id == assignment["id"],
            AuditLogEntry.action == "deleted",
        )
        .all()
    )
    assert len(entries) == 1
    assert entries[0].actor_user_id is not None


def test_reschedule_uses_a_locked_crews_remaining_free_time_for_other_runs(client, admin_headers):
    """A lock protects the specific assignment, not the crew's whole
    day (spec section 21) — only crew1 exists in this scenario, so
    this only passes if its non-busy time (everything except the
    locked run's [360,410] slot) is still usable for the other two
    runs. Deterministic (unlike a two-crew version of this test would
    be): the solver has no other crew to choose, so there's no tie for
    CP-SAT's objective to break arbitrarily between."""
    _school, _driver, _vehicle, crew1, runs = _seed_spec_section5_scenario(client, admin_headers)

    first = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert first.status_code == 200
    assignments = first.json()["assignments"]
    assert all(a["crew_id"] == crew1["id"] for a in assignments)

    locked_run_id = runs[0]["id"]
    locked_assignment = next(a for a in assignments if a["run_id"] == locked_run_id)
    lock_response = client.patch(
        f"/schedule/assignments/{locked_assignment['id']}",
        headers=admin_headers,
        json={"locked": True},
    )
    assert lock_response.status_code == 200

    second = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert second.status_code == 200, second.text
    body = second.json()
    assert len(body["assignments"]) == 3
    assert body["crews_used"] == 1

    by_run = {a["run_id"]: a for a in body["assignments"]}
    assert by_run[locked_run_id]["id"] == locked_assignment["id"]
    assert by_run[locked_run_id]["crew_id"] == crew1["id"]
    for run in runs[1:]:
        assert by_run[run["id"]]["crew_id"] == crew1["id"]


def test_reschedule_when_everything_locked_is_a_noop(client, admin_headers, db_session):
    _seed_spec_section5_scenario(client, admin_headers)
    first = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assignments = first.json()["assignments"]
    for a in assignments:
        r = client.patch(
            f"/schedule/assignments/{a['id']}", headers=admin_headers, json={"locked": True}
        )
        assert r.status_code == 200

    audit_count_before = (
        db_session.query(AuditLogEntry).filter(AuditLogEntry.entity_type == "assignment").count()
    )

    second = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert second.status_code == 200
    body = second.json()
    assert {a["id"] for a in body["assignments"]} == {a["id"] for a in assignments}
    assert body["crews_used"] == 1

    audit_count_after = (
        db_session.query(AuditLogEntry).filter(AuditLogEntry.entity_type == "assignment").count()
    )
    assert audit_count_after == audit_count_before  # nothing changed, nothing audited


def test_reschedule_still_infeasible_when_a_locked_busy_interval_blocks_the_only_crew(
    client, admin_headers
):
    """Partial-day availability frees up a locked crew's *other* time —
    it doesn't make locking meaningless. If the only remaining crew's
    free time genuinely can't fit an unlocked run, that must still be
    reported as infeasible, just via the solver's own CP-SAT
    infeasibility (busy_intervals constraint) rather than the old
    up-front "crew list is empty" check this scenario used to hit."""
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "S", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 410,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    )
    _add_crew(client, admin_headers, label="A")  # only crew

    first = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert first.status_code == 200
    assignment = first.json()["assignments"][0]
    lock_response = client.patch(
        f"/schedule/assignments/{assignment['id']}",
        headers=admin_headers,
        json={"locked": True},
    )
    assert lock_response.status_code == 200

    # Added after locking: its only possible window ([400,450])
    # overlaps run_a's now-busy [360,410] slot on the only crew.
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 400,
            "window_latest": 450,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    )

    second = client.post("/schedule", headers=admin_headers, json={"service_date": "2026-09-01"})
    assert second.status_code == 422
