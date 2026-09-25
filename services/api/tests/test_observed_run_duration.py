"""spec section 20: historical learning applied to Run.duration_minutes.
GET /runs/observed-duration is computed entirely from data this system
already persists (completed Assignments + their own status_changed
audit entries) -- no new history table. See routers/runs.py's
get_observed_run_duration docstring for the full reasoning."""

from datetime import UTC, datetime, timedelta

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _seed_scenario(client, admin_headers, *, service_date="2026-09-01"):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside Elementary", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
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
    client.post(
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
        },
    )
    schedule = client.post(
        "/schedule", headers=admin_headers, json={"service_date": service_date}
    ).json()
    assignment_id = schedule["assignments"][0]["id"]
    return school, driver, assignment_id


def _complete_assignment_with_duration(
    client, admin_headers, db_session, driver_id, assignment_id, *, actual_minutes
):
    """Drives an assignment through in_progress -> completed as its
    driver, then overwrites the two status_changed audit entries'
    created_at directly (real API calls happen too fast apart to
    exercise a meaningful multi-minute duration) so the test controls
    the exact "actual" duration the endpoint should compute."""
    make_user(
        db_session, email=f"driver{driver_id}@example.org", role=Role.DRIVER, driver_id=driver_id
    )
    token = login(client, email=f"driver{driver_id}@example.org")
    headers = auth_headers(token)
    client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=headers,
        json={"status": "in_progress"},
    )
    client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=headers,
        json={"status": "completed"},
    )

    entries = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "assignment",
            AuditLogEntry.entity_id == assignment_id,
            AuditLogEntry.action == "status_changed",
        )
        .order_by(AuditLogEntry.id)
        .all()
    )
    started_entry = next(e for e in entries if e.after_state["status"] == "in_progress")
    completed_entry = next(e for e in entries if e.after_state["status"] == "completed")
    started_entry.created_at = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
    completed_entry.created_at = started_entry.created_at + timedelta(minutes=actual_minutes)
    db_session.commit()


def test_observed_duration_is_empty_before_any_completed_assignment(client, admin_headers):
    school, _driver, _assignment_id = _seed_scenario(client, admin_headers)
    response = client.get(
        "/runs/observed-duration",
        headers=admin_headers,
        params={"school_id": school["id"], "direction": "am"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "sample_count": 0,
        "average_actual_minutes": None,
        "most_recent_actual_minutes": None,
        "most_recent_service_date": None,
    }


def test_observed_duration_computes_from_a_single_completed_assignment(
    client, admin_headers, db_session
):
    school, driver, assignment_id = _seed_scenario(client, admin_headers)
    _complete_assignment_with_duration(
        client, admin_headers, db_session, driver["id"], assignment_id, actual_minutes=48
    )

    response = client.get(
        "/runs/observed-duration",
        headers=admin_headers,
        params={"school_id": school["id"], "direction": "am"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sample_count"] == 1
    assert body["average_actual_minutes"] == 48.0
    assert body["most_recent_actual_minutes"] == 48
    assert body["most_recent_service_date"] == "2026-09-01"


def test_observed_duration_averages_across_multiple_completed_assignments(
    client, admin_headers, db_session
):
    school, driver, assignment_id = _seed_scenario(client, admin_headers, service_date="2026-09-01")
    _complete_assignment_with_duration(
        client, admin_headers, db_session, driver["id"], assignment_id, actual_minutes=40
    )

    driver2 = client.post(
        "/drivers",
        headers=admin_headers,
        json={"license_class": "cdl_a", "full_name": "Sam Substitute"},
    ).json()
    vehicle2 = client.post("/vehicles", headers=admin_headers, json={"label": "Bus 202"}).json()
    client.post(
        "/crews",
        headers=admin_headers,
        json={
            "service_date": "2026-09-02",
            "driver_id": driver2["id"],
            "vehicle_id": vehicle2["id"],
            "available_window_earliest": 0,
            "available_window_latest": 1439,
        },
    )
    client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": "2026-09-02",
            "school_id": school["id"],
            "direction": "am",
            "window_earliest": 360,
            "window_latest": 420,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    )
    schedule2 = client.post(
        "/schedule", headers=admin_headers, json={"service_date": "2026-09-02"}
    ).json()
    assignment2_id = schedule2["assignments"][0]["id"]
    make_user(db_session, email="driver_sam@example.org", role=Role.DRIVER, driver_id=driver2["id"])
    token2 = login(client, email="driver_sam@example.org")
    headers2 = auth_headers(token2)
    client.patch(
        f"/schedule/assignments/{assignment2_id}/status",
        headers=headers2,
        json={"status": "in_progress"},
    )
    client.patch(
        f"/schedule/assignments/{assignment2_id}/status",
        headers=headers2,
        json={"status": "completed"},
    )
    entries2 = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "assignment",
            AuditLogEntry.entity_id == assignment2_id,
            AuditLogEntry.action == "status_changed",
        )
        .order_by(AuditLogEntry.id)
        .all()
    )
    started2 = next(e for e in entries2 if e.after_state["status"] == "in_progress")
    completed2 = next(e for e in entries2 if e.after_state["status"] == "completed")
    started2.created_at = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
    completed2.created_at = started2.created_at + timedelta(minutes=56)
    db_session.commit()

    response = client.get(
        "/runs/observed-duration",
        headers=admin_headers,
        params={"school_id": school["id"], "direction": "am"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sample_count"] == 2
    assert body["average_actual_minutes"] == 48.0
    assert body["most_recent_actual_minutes"] == 56
    assert body["most_recent_service_date"] == "2026-09-02"


def test_observed_duration_ignores_an_assignment_still_in_progress(
    client, admin_headers, db_session
):
    school, driver, assignment_id = _seed_scenario(client, admin_headers)
    make_user(db_session, email="driver_wip@example.org", role=Role.DRIVER, driver_id=driver["id"])
    token = login(client, email="driver_wip@example.org")
    client.patch(
        f"/schedule/assignments/{assignment_id}/status",
        headers=auth_headers(token),
        json={"status": "in_progress"},
    )

    response = client.get(
        "/runs/observed-duration",
        headers=admin_headers,
        params={"school_id": school["id"], "direction": "am"},
    )
    assert response.json()["sample_count"] == 0


def test_observed_duration_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    school, _driver, _assignment_id = _seed_scenario(client, admin_headers)
    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.get(
        "/runs/observed-duration",
        headers=auth_headers(token),
        params={"school_id": school["id"], "direction": "am"},
    )
    assert response.status_code == 403
