"""spec section 9: driver-app incident reporting / vehicle defect
reporting. One DriverReport entity with a report_type discriminator --
see routers/driver_reports.py's module docstring."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _seed_driver_with_crew(client, admin_headers, *, service_date="2026-09-01"):
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Jordan Driver"},
    ).json()
    vehicle = client.post("/vehicles", headers=admin_headers, json={"label": "Bus 101"}).json()
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    )
    return driver, vehicle


def _login_as_driver(client, db_session, driver_id, *, email="driver1@example.org"):
    make_user(db_session, email=email, role=Role.DRIVER, driver_id=driver_id)
    token = login(client, email=email)
    return auth_headers(token)


def test_create_report_round_trips_and_resolves_vehicle_from_crew(
    client, admin_headers, db_session
):
    driver, vehicle = _seed_driver_with_crew(client, admin_headers)
    driver_headers = _login_as_driver(client, db_session, driver["id"])

    response = client.post(
        f"/drivers/{driver['id']}/reports",
        headers=driver_headers,
        json={
            "service_date": "2026-09-01",
            "report_type": "vehicle_defect",
            "description": "Brake pedal feels soft.",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["report_type"] == "vehicle_defect"
    assert body["description"] == "Brake pedal feels soft."
    assert body["vehicle_id"] == vehicle["id"]


def test_create_report_leaves_vehicle_null_with_no_crew_that_date(
    client, admin_headers, db_session
):
    driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Unscheduled Driver"},
    ).json()
    driver_headers = _login_as_driver(client, db_session, driver["id"])

    response = client.post(
        f"/drivers/{driver['id']}/reports",
        headers=driver_headers,
        json={
            "service_date": "2026-09-01",
            "report_type": "incident",
            "description": "Near-miss with a cyclist at Elm & 5th.",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["vehicle_id"] is None


def test_create_report_is_audited(client, admin_headers, db_session):
    driver, _vehicle = _seed_driver_with_crew(client, admin_headers)
    driver_headers = _login_as_driver(client, db_session, driver["id"])
    response = client.post(
        f"/drivers/{driver['id']}/reports",
        headers=driver_headers,
        json={
            "service_date": "2026-09-01",
            "report_type": "incident",
            "description": "Minor fender bender in the bus lot.",
        },
    )
    report_id = response.json()["id"]
    entries = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "driver_report", AuditLogEntry.entity_id == report_id)
        .all()
    )
    assert len(entries) == 1
    assert entries[0].action == "created"


def test_staff_can_file_a_report_on_a_drivers_behalf(client, admin_headers, db_session):
    driver, _vehicle = _seed_driver_with_crew(client, admin_headers)
    response = client.post(
        f"/drivers/{driver['id']}/reports",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "report_type": "incident",
            "description": "Reported by phone from the driver.",
        },
    )
    assert response.status_code == 201, response.text


def test_driver_cannot_file_a_report_for_another_driver(client, admin_headers, db_session):
    driver, _vehicle = _seed_driver_with_crew(client, admin_headers)
    other_driver = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Other Driver"},
    ).json()
    other_headers = _login_as_driver(
        client, db_session, other_driver["id"], email="driver2@example.org"
    )
    response = client.post(
        f"/drivers/{driver['id']}/reports",
        headers=other_headers,
        json={
            "service_date": "2026-09-01",
            "report_type": "incident",
            "description": "Not allowed",
        },
    )
    assert response.status_code == 403


def test_create_report_rejects_unknown_driver(client, admin_headers):
    response = client.post(
        "/drivers/999/reports",
        headers=admin_headers,
        json={
            "service_date": "2026-09-01",
            "report_type": "incident",
            "description": "Unknown driver",
        },
    )
    assert response.status_code == 404


def test_list_all_reports_for_a_date(client, admin_headers, db_session):
    driver, _vehicle = _seed_driver_with_crew(client, admin_headers)
    driver_headers = _login_as_driver(client, db_session, driver["id"])
    client.post(
        f"/drivers/{driver['id']}/reports",
        headers=driver_headers,
        json={
            "service_date": "2026-09-01",
            "report_type": "vehicle_defect",
            "description": "Squeaky brakes.",
        },
    )
    client.post(
        f"/drivers/{driver['id']}/reports",
        headers=driver_headers,
        json={
            "service_date": "2026-09-02",
            "report_type": "incident",
            "description": "A different day, should not show up.",
        },
    )

    response = client.get("/reports", headers=admin_headers, params={"service_date": "2026-09-01"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["description"] == "Squeaky brakes."


def test_list_all_reports_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.get(
        "/reports", headers=auth_headers(token), params={"service_date": "2026-09-01"}
    )
    assert response.status_code == 403
