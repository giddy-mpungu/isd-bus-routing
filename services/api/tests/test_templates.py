"""Recurring route/crew templates and generate-from-templates
(spec section 11 "Permanent Assignment", ADR 0001's Route)."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

MONDAY = "2026-09-21"
TUESDAY = "2026-09-22"
SATURDAY = "2026-09-19"
WEEKDAYS = [0, 1, 2, 3, 4]


def _seed_school(client, admin_headers, name="Riverside Elementary"):
    return client.post(
        "/schools",
        headers=admin_headers,
        json={"name": name, "location_lat": 29.70, "location_lon": -95.40},
    ).json()


def _seed_driver_vehicle(client, admin_headers, label="A"):
    driver = client.post("/drivers", headers=admin_headers, json={"full_name": f"Driver {label}"})
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": f"Bus {label}"})
    return driver.json(), vehicle.json()


def _route_template_payload(school_id, **overrides):
    payload = {
        "school_id": school_id,
        "direction": "am",
        "window_earliest": 360,
        "window_latest": 450,
        "duration_minutes": 40,
        "buffer_minutes": 10,
        "days_of_week": WEEKDAYS,
    }
    payload.update(overrides)
    return payload


def _crew_template_payload(driver_id, vehicle_id, **overrides):
    payload = {
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "available_window_earliest": 300,
        "available_window_latest": 900,
        "days_of_week": WEEKDAYS,
    }
    payload.update(overrides)
    return payload


def _generate(client, headers, service_date):
    return client.post(f"/schedule/{service_date}/generate-from-templates", headers=headers)


def test_route_template_round_trips_all_fields(client, admin_headers):
    school = _seed_school(client, admin_headers)
    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": "wheelchair_lift", "kind": "vehicle_capability"},
    )
    response = client.post(
        "/route-templates",
        headers=admin_headers,
        json=_route_template_payload(
            school["id"],
            direction="pm",
            days_of_week=[4, 0, 2],
            active_from="2026-09-01",
            active_until="2026-12-18",
            required_qualification_codes=["wheelchair_lift"],
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["direction"] == "pm"
    assert body["days_of_week"] == [0, 2, 4]  # normalized to sorted order
    assert body["active_from"] == "2026-09-01"
    assert body["active_until"] == "2026-12-18"
    assert body["is_active"] is True
    assert [q["code"] for q in body["required_qualifications"]] == ["wheelchair_lift"]

    listed = client.get("/route-templates", headers=admin_headers).json()
    assert [t["id"] for t in listed] == [body["id"]]


def test_route_template_validation(client, admin_headers):
    school = _seed_school(client, admin_headers)
    sid = school["id"]
    bad_payloads = [
        _route_template_payload(sid, days_of_week=[]),
        _route_template_payload(sid, days_of_week=[7]),
        _route_template_payload(sid, days_of_week=[1, 1]),
        _route_template_payload(sid, window_earliest=500, window_latest=400),
        _route_template_payload(sid, duration_minutes=90, buffer_minutes=10),
        _route_template_payload(sid, active_from="2026-12-01", active_until="2026-09-01"),
        _route_template_payload(9999),
    ]
    for payload in bad_payloads:
        response = client.post("/route-templates", headers=admin_headers, json=payload)
        assert response.status_code in (400, 422), (payload, response.text)
    assert client.get("/route-templates", headers=admin_headers).json() == []


def test_crew_template_validation(client, admin_headers):
    driver, vehicle = _seed_driver_vehicle(client, admin_headers)
    bad_payloads = [
        _crew_template_payload(driver["id"], vehicle["id"], days_of_week=[]),
        _crew_template_payload(
            driver["id"], vehicle["id"], available_window_earliest=900, available_window_latest=300
        ),
        _crew_template_payload(9999, vehicle["id"]),
        _crew_template_payload(driver["id"], 9999),
        _crew_template_payload(
            driver["id"], vehicle["id"], active_from="2026-12-01", active_until="2026-09-01"
        ),
    ]
    for payload in bad_payloads:
        response = client.post("/crew-templates", headers=admin_headers, json=payload)
        assert response.status_code in (400, 422), (payload, response.text)


def test_template_endpoints_are_admin_and_dispatcher_only(client, admin_headers, db_session):
    school = _seed_school(client, admin_headers)
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    make_user(db_session, email="drv@example.org", role=Role.DRIVER)
    make_user(db_session, email="sch@example.org", role=Role.SCHOOL_ADMIN, school_id=school["id"])

    dispatcher = auth_headers(login(client, email="disp@example.org"))
    created = client.post(
        "/route-templates", headers=dispatcher, json=_route_template_payload(school["id"])
    )
    assert created.status_code == 201, created.text

    for email in ("drv@example.org", "sch@example.org"):
        headers = auth_headers(login(client, email=email))
        assert client.get("/route-templates", headers=headers).status_code == 403
        assert client.get("/crew-templates", headers=headers).status_code == 403
        assert (
            client.post(
                "/route-templates", headers=headers, json=_route_template_payload(school["id"])
            ).status_code
            == 403
        )
        assert (
            client.patch(
                f"/route-templates/{created.json()['id']}",
                headers=headers,
                json={"is_active": False},
            ).status_code
            == 403
        )
        assert _generate(client, headers, MONDAY).status_code == 403

    assert client.get("/route-templates").status_code in (401, 403)
    assert client.post(f"/schedule/{MONDAY}/generate-from-templates").status_code in (401, 403)


def test_generate_creates_runs_and_crews_only_on_matching_weekdays(client, admin_headers):
    school = _seed_school(client, admin_headers)
    driver, vehicle = _seed_driver_vehicle(client, admin_headers)
    client.post(
        "/route-templates", headers=admin_headers, json=_route_template_payload(school["id"])
    )
    client.post(
        "/crew-templates",
        headers=admin_headers,
        json=_crew_template_payload(driver["id"], vehicle["id"]),
    )

    weekday = _generate(client, admin_headers, MONDAY)
    assert weekday.status_code == 200, weekday.text
    assert weekday.json()["runs_created"] == 1
    assert weekday.json()["crews_created"] == 1

    runs = client.get("/runs", headers=admin_headers, params={"service_date": MONDAY}).json()
    assert len(runs) == 1
    assert runs[0]["school_id"] == school["id"]
    assert runs[0]["direction"] == "am"
    assert (runs[0]["window_earliest"], runs[0]["window_latest"]) == (360, 450)
    assert (runs[0]["duration_minutes"], runs[0]["buffer_minutes"]) == (40, 10)
    crews = client.get("/crews", headers=admin_headers, params={"service_date": MONDAY}).json()
    assert len(crews) == 1
    assert (crews[0]["driver_id"], crews[0]["vehicle_id"]) == (driver["id"], vehicle["id"])

    saturday = _generate(client, admin_headers, SATURDAY).json()
    assert saturday["runs_created"] == 0
    assert saturday["crews_created"] == 0
    assert (
        client.get("/runs", headers=admin_headers, params={"service_date": SATURDAY}).json() == []
    )


def test_generate_is_idempotent(client, admin_headers):
    school = _seed_school(client, admin_headers)
    driver, vehicle = _seed_driver_vehicle(client, admin_headers)
    client.post(
        "/route-templates", headers=admin_headers, json=_route_template_payload(school["id"])
    )
    client.post(
        "/crew-templates",
        headers=admin_headers,
        json=_crew_template_payload(driver["id"], vehicle["id"]),
    )
    _generate(client, admin_headers, MONDAY)
    second = _generate(client, admin_headers, MONDAY).json()

    assert second["runs_created"] == 0
    assert second["runs_already_existing"] == 1
    assert second["crews_created"] == 0
    assert second["crews_already_existing"] == 1
    assert (
        len(client.get("/runs", headers=admin_headers, params={"service_date": MONDAY}).json()) == 1
    )
    assert (
        len(client.get("/crews", headers=admin_headers, params={"service_date": MONDAY}).json())
        == 1
    )


def test_generate_honors_active_date_range_and_deactivation(client, admin_headers):
    school = _seed_school(client, admin_headers)
    template = client.post(
        "/route-templates",
        headers=admin_headers,
        json=_route_template_payload(
            school["id"], active_from="2026-09-22", active_until="2026-09-22"
        ),
    ).json()

    assert _generate(client, admin_headers, MONDAY).json()["runs_created"] == 0  # before range
    assert _generate(client, admin_headers, "2026-09-23").json()["runs_created"] == 0  # after
    assert _generate(client, admin_headers, TUESDAY).json()["runs_created"] == 1

    deactivated = client.patch(
        f"/route-templates/{template['id']}", headers=admin_headers, json={"is_active": False}
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert _generate(client, admin_headers, TUESDAY).json()["runs_created"] == 0
    # Already-generated history is untouched by deactivation.
    assert (
        len(client.get("/runs", headers=admin_headers, params={"service_date": TUESDAY}).json())
        == 1
    )


def test_generate_never_overwrites_existing_day_level_edits(client, admin_headers):
    """A dispatcher's manual edit to a generated day survives re-generation."""
    school = _seed_school(client, admin_headers)
    driver_a, vehicle_a = _seed_driver_vehicle(client, admin_headers, "A")
    driver_b, _ = _seed_driver_vehicle(client, admin_headers, "B")
    client.post(
        "/route-templates", headers=admin_headers, json=_route_template_payload(school["id"])
    )
    client.post(
        "/crew-templates",
        headers=admin_headers,
        json=_crew_template_payload(driver_a["id"], vehicle_a["id"]),
    )
    _generate(client, admin_headers, MONDAY)
    run = client.get("/runs", headers=admin_headers, params={"service_date": MONDAY}).json()[0]
    crew = client.get("/crews", headers=admin_headers, params={"service_date": MONDAY}).json()[0]

    client.patch(f"/runs/{run['id']}", headers=admin_headers, json={"passenger_count": 33})
    client.patch(f"/crews/{crew['id']}", headers=admin_headers, json={"driver_id": driver_b["id"]})

    _generate(client, admin_headers, MONDAY)

    runs = client.get("/runs", headers=admin_headers, params={"service_date": MONDAY}).json()
    crews = client.get("/crews", headers=admin_headers, params={"service_date": MONDAY}).json()
    assert [r["passenger_count"] for r in runs] == [33]
    assert [c["driver_id"] for c in crews] == [driver_b["id"]]  # substitute kept, no duplicate


def test_generate_skips_crew_when_driver_or_vehicle_already_has_a_crew(client, admin_headers):
    driver_a, vehicle_a = _seed_driver_vehicle(client, admin_headers, "A")
    driver_b, vehicle_b = _seed_driver_vehicle(client, admin_headers, "B")
    # Hand-made crew already uses driver A on Monday, paired with a different bus.
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": MONDAY,
            "driver_id": driver_a["id"],
            "vehicle_id": vehicle_b["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1000,
        },
    )
    client.post(
        "/crew-templates",
        headers=admin_headers,
        json=_crew_template_payload(driver_a["id"], vehicle_a["id"]),
    )
    client.post(
        "/crew-templates",
        headers=admin_headers,
        json=_crew_template_payload(driver_b["id"], vehicle_b["id"]),
    )

    result = _generate(client, admin_headers, MONDAY)
    assert result.status_code == 200, result.text
    assert result.json()["crews_created"] == 0
    assert result.json()["crews_already_existing"] == 2
    assert (
        len(client.get("/crews", headers=admin_headers, params={"service_date": MONDAY}).json())
        == 1
    )


def test_generate_skips_crew_for_fully_absent_driver_but_not_partial(client, admin_headers):
    driver_a, vehicle_a = _seed_driver_vehicle(client, admin_headers, "A")
    driver_b, vehicle_b = _seed_driver_vehicle(client, admin_headers, "B")
    for driver, vehicle in ((driver_a, vehicle_a), (driver_b, vehicle_b)):
        client.post(
            "/crew-templates",
            headers=admin_headers,
            json=_crew_template_payload(driver["id"], vehicle["id"]),
        )
    # A is out all day; B is out only for the early morning.
    client.post(
        f"/drivers/{driver_a['id']}/absences",
        headers=admin_headers,
        json={
            "service_date": MONDAY,
            "start_minute": 0,
            "end_minute": 1439,
            "reason": "sick_leave",
        },
    )
    client.post(
        f"/drivers/{driver_b['id']}/absences",
        headers=admin_headers,
        json={"service_date": MONDAY, "start_minute": 0, "end_minute": 400, "reason": "sick_leave"},
    )

    result = _generate(client, admin_headers, MONDAY).json()
    assert result["crews_created"] == 1
    assert result["crews_skipped_absent_driver_ids"] == [driver_a["id"]]
    crews = client.get("/crews", headers=admin_headers, params={"service_date": MONDAY}).json()
    assert [c["driver_id"] for c in crews] == [driver_b["id"]]


def test_generated_runs_carry_required_qualifications_and_solve_end_to_end(client, admin_headers):
    school = _seed_school(client, admin_headers)
    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": "wheelchair_lift", "kind": "vehicle_capability"},
    )
    driver = client.post("/drivers", headers=admin_headers, json={"full_name": "Driver Q"}).json()
    vehicle = client.post(
        "/vehicles",
        headers=admin_headers,
        json={"label": "Lift Bus", "qualification_codes": ["wheelchair_lift"]},
    ).json()
    client.post(
        "/route-templates",
        headers=admin_headers,
        json=_route_template_payload(
            school["id"], required_qualification_codes=["wheelchair_lift"]
        ),
    )
    client.post(
        "/crew-templates",
        headers=admin_headers,
        json=_crew_template_payload(driver["id"], vehicle["id"]),
    )

    _generate(client, admin_headers, MONDAY)
    run = client.get("/runs", headers=admin_headers, params={"service_date": MONDAY}).json()[0]
    assert [q["code"] for q in run["required_qualifications"]] == ["wheelchair_lift"]

    solved = client.post(
        "/schedule",
        headers=admin_headers,
        json={"service_date": MONDAY, "average_deadhead_speed_kmh": 40.0},
    )
    assert solved.status_code == 200, solved.text
    assert len(solved.json()["assignments"]) == 1
    assert solved.json()["assignments"][0]["run_id"] == run["id"]


def test_generation_and_template_changes_are_audited(client, admin_headers, db_session):
    school = _seed_school(client, admin_headers)
    driver, vehicle = _seed_driver_vehicle(client, admin_headers)
    route_template = client.post(
        "/route-templates", headers=admin_headers, json=_route_template_payload(school["id"])
    ).json()
    client.post(
        "/crew-templates",
        headers=admin_headers,
        json=_crew_template_payload(driver["id"], vehicle["id"]),
    )
    client.patch(
        f"/route-templates/{route_template['id']}", headers=admin_headers, json={"is_active": True}
    )
    _generate(client, admin_headers, MONDAY)

    actions = {(e.entity_type, e.action) for e in db_session.query(AuditLogEntry).all()}
    assert ("route_template", "created") in actions
    assert ("route_template", "updated") in actions
    assert ("crew_template", "created") in actions
    assert ("run", "generated_from_template") in actions
    assert ("crew", "generated_from_template") in actions


def test_patch_unknown_template_is_404(client, admin_headers):
    assert (
        client.patch(
            "/route-templates/999", headers=admin_headers, json={"is_active": False}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            "/crew-templates/999", headers=admin_headers, json={"is_active": False}
        ).status_code
        == 404
    )
