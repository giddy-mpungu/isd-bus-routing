"""Fleet maintenance (isd_api/maintenance.py): maintenance windows, service
and inspection dates, defect reports tracked to resolution, and spare
buses. The district clock is pinned to 2026-08-01 07:00 (America/Chicago)."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user

MONDAY = "2026-09-21"
TODAY = "2026-08-01"
WEEKDAYS = [0, 1, 2, 3, 4, 5, 6]


def _school(client, h):
    return client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside Elementary", "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _bus(client, h, label, **extra):
    response = client.post("/vehicles", headers=h, json={"label": label, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _driver(client, h, name="Driver A", license_class="cdl_a"):
    return client.post(
        "/drivers", headers=h, json={"license_class": license_class, "full_name": name}
    ).json()


def _crew_template(client, h, driver, bus):
    response = client.post(
        "/crew-templates",
        headers=h,
        json={
            "driver_id": driver["id"],
            "vehicle_id": bus["id"],
            "available_window_earliest": 300,
            "available_window_latest": 1000,
            "days_of_week": WEEKDAYS,
        },
    )
    assert response.status_code == 201, response.text


def _route(client, h, school, **extra):
    response = client.post(
        "/route-templates",
        headers=h,
        json={
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 400,
            "window_latest": 480,
            "duration_minutes": 40,
            "buffer_minutes": 0,
            "days_of_week": WEEKDAYS,
            **extra,
        },
    )
    assert response.status_code == 201, response.text


def _day(client, h, day):
    generated = client.post(f"/schedule/{day}/generate-from-templates", headers=h).json()
    solved = client.post(
        "/schedule", headers=h, json={"service_date": day, "average_deadhead_speed_kmh": 40.0}
    )
    return generated, solved


def _window(client, h, bus, starts, ends=None, **extra):
    return client.post(
        "/maintenance/windows",
        headers=h,
        json={
            "vehicle_id": bus["id"],
            "starts_at": starts,
            "ends_at": ends,
            "reason": "Brake service",
            **extra,
        },
    )


def _alerts(client, h, day, kind):
    body = client.get("/alerts", headers=h, params={"service_date": day}).json()
    return [a for a in body["alerts"] if a["kind"] == kind]


def _one_bus_day(client, h, **bus_extra):
    """A route and a crew (Driver A on Bus 1) that the solver pairs on MONDAY."""
    school = _school(client, h)
    _route(client, h, school)
    driver = _driver(client, h)
    bus = _bus(client, h, "Bus 1", **bus_extra)
    _crew_template(client, h, driver, bus)
    return school, driver, bus


def test_a_bus_in_maintenance_isnt_scheduled_then(client, admin_headers):
    _school_, _driver_, bus = _one_bus_day(client, admin_headers)
    assert (
        _window(client, admin_headers, bus, f"{MONDAY}T06:00", f"{MONDAY}T09:00").status_code == 201
    )
    _, solved = _day(client, admin_headers, MONDAY)
    # No crew can take the run: the solver refuses rather than schedule the bus.
    assert solved.status_code >= 400, solved.text


def test_a_bus_out_all_day_frees_its_driver_at_generation(client, admin_headers):
    _school_, _driver_, bus = _one_bus_day(client, admin_headers)
    _window(client, admin_headers, bus, f"{MONDAY}T00:00", "2026-09-22T00:00")
    generated, _ = _day(client, admin_headers, MONDAY)
    assert generated["crews_created"] == 0
    assert generated["crews_skipped_out_of_service_template_ids"]


def test_losing_a_bus_after_scheduling_offers_spares_and_swaps_one_in(
    client, admin_headers, db_session
):
    _school_, driver, bus = _one_bus_day(client, admin_headers)
    _, solved = _day(client, admin_headers, MONDAY)
    [assignment] = solved.json()["assignments"]

    spare = _bus(client, admin_headers, "Spare 9", nominal_capacity=40)
    _bus(client, admin_headers, "Lift Bus", qualification_codes=[])  # also free
    tiny = _bus(client, admin_headers, "Van 2", nominal_capacity=1)
    client.patch(
        f"/runs/{assignment['run_id']}", headers=admin_headers, json={"passenger_count": 10}
    )

    _window(client, admin_headers, bus, f"{MONDAY}T05:00", None, kind="repair")
    [alert] = _alerts(client, admin_headers, MONDAY, "needs_bus")
    assert alert["severity"] == "critical"
    assert "Bus 1 in maintenance (Brake service, until fixed)" in alert["message"]
    assert not _alerts(client, admin_headers, MONDAY, "needs_cover")

    crews = client.get("/crews", headers=admin_headers, params={"service_date": MONDAY}).json()
    crew = next(c for c in crews if c["vehicle_id"] == bus["id"])
    offered = client.get(
        f"/assignments/{alert['entity_id']}/spare-vehicles", headers=admin_headers
    ).json()
    assert offered["crew_id"] == crew["id"] and offered["current_vehicle_label"] == "Bus 1"
    labels = [s["label"] for s in offered["spares"]]
    assert "Spare 9" in labels and "Van 2" not in labels and "Bus 1" not in labels

    refused = client.put(
        f"/crews/{crew['id']}/vehicle", headers=admin_headers, json={"vehicle_id": tiny["id"]}
    )
    assert refused.status_code == 409
    swapped = client.put(
        f"/crews/{crew['id']}/vehicle", headers=admin_headers, json={"vehicle_id": spare["id"]}
    )
    assert swapped.status_code == 200 and swapped.json()["vehicle_id"] == spare["id"]
    assert not _alerts(client, admin_headers, MONDAY, "needs_bus")
    assert db_session.query(AuditLogEntry).filter_by(action="vehicle_swapped").count() == 1


def test_spares_respect_the_drivers_license_and_capabilities(client, admin_headers):
    school = _school(client, admin_headers)
    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": "wheelchair_lift", "kind": "vehicle_capability"},
    )
    _route(client, admin_headers, school, required_qualification_codes=["wheelchair_lift"])
    driver = _driver(client, admin_headers, license_class="class_c")
    bus = _bus(
        client,
        admin_headers,
        "Lift 1",
        nominal_capacity=10,
        qualification_codes=["wheelchair_lift"],
    )
    _crew_template(client, admin_headers, driver, bus)
    _day(client, admin_headers, MONDAY)
    _bus(client, admin_headers, "No lift", nominal_capacity=10)
    _bus(
        client,
        admin_headers,
        "Big lift",
        nominal_capacity=70,
        qualification_codes=["wheelchair_lift"],
    )
    good = _bus(
        client,
        admin_headers,
        "Lift 2",
        nominal_capacity=10,
        qualification_codes=["wheelchair_lift"],
    )
    [assignment] = client.get(f"/schedule/{MONDAY}/assignments", headers=admin_headers).json()
    spares = client.get(
        f"/assignments/{assignment['id']}/spare-vehicles", headers=admin_headers
    ).json()["spares"]
    # No lift: missing the capability; Big lift: needs a CDL the driver lacks.
    assert [s["vehicle_id"] for s in spares] == [good["id"]]


def test_an_expired_inspection_keeps_a_bus_off_the_schedule(client, admin_headers):
    _school_, _driver_, bus = _one_bus_day(client, admin_headers)
    dates = client.put(
        f"/vehicles/{bus['id']}/maintenance-dates",
        headers=admin_headers,
        json={"inspection_expires_on": "2026-09-20", "service_due_on": "2026-09-30"},
    )
    assert dates.status_code == 200
    _, solved = _day(client, admin_headers, MONDAY)
    # No crew can take the run: the solver refuses rather than schedule the bus.
    assert solved.status_code >= 400, solved.text
    due = {
        a["severity"]: a["message"] for a in _alerts(client, admin_headers, MONDAY, "vehicle_due")
    }
    assert "inspection expired on 2026-09-20" in due["critical"]
    assert "service is due on 2026-09-30" in due["warning"]

    # Valid through its expiry date.
    _, solved = _day(client, admin_headers, "2026-09-20")
    assert len(solved.json()["assignments"]) == 1


def test_service_log_and_due_list(client, admin_headers):
    bus = _bus(client, admin_headers, "Bus 1")
    other = _bus(client, admin_headers, "Bus 2")
    client.put(
        f"/vehicles/{other['id']}/maintenance-dates",
        headers=admin_headers,
        json={"service_due_on": "2026-08-10"},
    )
    logged = client.post(
        f"/vehicles/{bus['id']}/service-records",
        headers=admin_headers,
        json={
            "performed_on": "2026-07-30",
            "work": "Oil and filters",
            "performed_by": "Fleet shop",
            "next_service_due_on": "2026-08-05",
            "inspection_expires_on": "2027-07-31",
        },
    )
    assert logged.status_code == 201, logged.text
    body = logged.json()
    assert body["service_due_on"] == "2026-08-05"
    assert body["inspection_expires_on"] == "2027-07-31"
    assert [r["work"] for r in body["service_log"]] == ["Oil and filters"]

    due = client.get("/maintenance/due", headers=admin_headers).json()
    assert [(d["vehicle_label"], d["severity"]) for d in due] == [
        ("Bus 1", "warning"),
        ("Bus 2", "warning"),
    ]


def test_a_defect_report_is_tracked_to_resolution(client, admin_headers, db_session):
    _school_, driver, bus = _one_bus_day(client, admin_headers)
    _day(client, admin_headers, TODAY)
    report = client.post(
        f"/drivers/{driver['id']}/reports",
        headers=admin_headers,
        json={
            "service_date": TODAY,
            "report_type": "vehicle_defect",
            "description": "Brakes squeal",
        },
    ).json()
    assert report["vehicle_id"] == bus["id"] and report["status"] == "open"
    assert _alerts(client, admin_headers, TODAY, "vehicle_defect")
    [listed] = client.get("/maintenance/defects", headers=admin_headers).json()
    assert listed["vehicle_label"] == "Bus 1" and listed["driver_name"] == "Driver A"

    out = client.post(
        f"/maintenance/defects/{report['id']}/out-of-service", headers=admin_headers, json={}
    )
    assert out.status_code == 200 and out.json()["status"] == "out_of_service"
    again = client.post(
        f"/maintenance/defects/{report['id']}/out-of-service", headers=admin_headers, json={}
    )
    assert again.status_code == 409
    # The open report's alert gives way to its runs needing a bus.
    assert not _alerts(client, admin_headers, TODAY, "vehicle_defect")
    [window] = client.get("/maintenance/windows", headers=admin_headers).json()
    assert window["current"] is True and window["kind"] == "repair"
    assert window["starts_at"].startswith("2026-08-01T07:00")
    assert window["driver_report_id"] == report["id"]

    fixed = client.post(
        f"/maintenance/defects/{report['id']}/fixed",
        headers=admin_headers,
        json={"note": "Pads replaced"},
    )
    assert fixed.json()["status"] == "fixed" and fixed.json()["resolution_note"] == "Pads replaced"
    assert client.get("/maintenance/windows", headers=admin_headers).json() == []
    assert client.get("/maintenance/defects", headers=admin_headers).json() == []
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert {"out_of_service_for_defect", "back_in_service", "defect_fixed"} <= actions


def test_ending_a_defect_window_marks_its_report_fixed(client, admin_headers):
    _school_, driver, _bus_ = _one_bus_day(client, admin_headers)
    _day(client, admin_headers, TODAY)
    report = client.post(
        f"/drivers/{driver['id']}/reports",
        headers=admin_headers,
        json={"service_date": TODAY, "report_type": "vehicle_defect", "description": "Door"},
    ).json()
    client.post(
        f"/maintenance/defects/{report['id']}/out-of-service", headers=admin_headers, json={}
    )
    [window] = client.get("/maintenance/windows", headers=admin_headers).json()
    assert (
        client.post(f"/maintenance/windows/{window['id']}/end", headers=admin_headers).status_code
        == 204
    )
    [listed] = client.get(
        "/maintenance/defects", headers=admin_headers, params={"status_filter": "all"}
    ).json()
    assert listed["status"] == "fixed"


def test_window_rules(client, admin_headers):
    bus = _bus(client, admin_headers, "Bus 1")
    backwards = _window(client, admin_headers, bus, f"{MONDAY}T10:00", f"{MONDAY}T09:00")
    assert backwards.status_code == 422
    future = _window(client, admin_headers, bus, f"{MONDAY}T06:00", f"{MONDAY}T09:00").json()
    assert future["current"] is False
    # Not started yet: ending it cancels it.
    assert (
        client.post(f"/maintenance/windows/{future['id']}/end", headers=admin_headers).status_code
        == 204
    )
    assert client.get("/maintenance/windows", headers=admin_headers).json() == []
    past = _window(client, admin_headers, bus, "2026-07-01T06:00", "2026-07-02T06:00").json()
    assert (
        client.post(f"/maintenance/windows/{past['id']}/end", headers=admin_headers).status_code
        == 409
    )
    every = client.get(
        "/maintenance/windows", headers=admin_headers, params={"include_past": True}
    ).json()
    assert [w["id"] for w in every] == [past["id"]]


def test_a_field_trip_cant_take_a_bus_in_maintenance(client, admin_headers):
    bus = _bus(client, admin_headers, "Bus 1")
    _window(client, admin_headers, bus, "2026-09-01T12:00", "2026-09-01T14:00")
    trip = client.post(
        "/field-trips",
        headers=admin_headers,
        json={
            "requesting_party": "Science Department",
            "origin": "Riverside Elementary",
            "destination": "State Science Museum",
            "departure_at": "2026-09-01T13:00:00",
            "expected_return_at": "2026-09-01T16:00:00",
            "passenger_count": 30,
            "trip_contact": "Ms. Rivera",
        },
    ).json()
    check = client.get(
        f"/field-trips/{trip['id']}/conflicts",
        headers=admin_headers,
        params={"vehicle_id": bus["id"]},
    ).json()
    assert any("Bus Bus 1 in maintenance" in c for c in check["conflicts"])


def test_only_transportation_staff_manage_maintenance(client, admin_headers, db_session):
    bus = _bus(client, admin_headers, "Bus 1")
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="disp@example.org"))
    assert _window(client, dispatcher, bus, f"{MONDAY}T06:00", f"{MONDAY}T09:00").status_code == 201
    for role, email in ((Role.DRIVER, "drv@example.org"), (Role.SCHOOL_ADMIN, "sa@example.org")):
        make_user(db_session, email=email, role=role)
        headers = auth_headers(login(client, email=email))
        assert client.get("/maintenance/windows", headers=headers).status_code == 403
        assert _window(client, headers, bus, f"{MONDAY}T06:00").status_code == 403
        assert client.get(f"/vehicles/{bus['id']}/maintenance", headers=headers).status_code == 403


def test_reports_from_before_this_feature_read_as_open(client, admin_headers, db_session):
    """Rows the migration upgrades get the column default: it must be a
    status the model can read (enum columns store the member's name)."""
    from sqlalchemy import text

    driver = _driver(client, admin_headers)
    db_session.execute(
        text(
            "INSERT INTO driver_reports (driver_id, service_date, report_type, description, "
            "created_at) VALUES (:d, :day, 'VEHICLE_DEFECT', 'Old report', CURRENT_TIMESTAMP)"
        ),
        {"d": driver["id"], "day": TODAY},
    )
    db_session.commit()
    [old] = client.get("/maintenance/defects", headers=admin_headers).json()
    assert old["status"] == "open" and old["description"] == "Old report"
