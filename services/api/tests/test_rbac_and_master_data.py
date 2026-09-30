from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user


def test_non_admin_cannot_create_user(client, db_session):
    make_user(db_session, email="dispatch@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatch@example.org")
    response = client.post(
        "/users",
        headers=auth_headers(token),
        json={
            "email": "x@example.org",
            "password": "route-pass-123",
            "full_name": "X",
            "role": "driver",
        },
    )
    assert response.status_code == 403


def test_admin_can_create_user(client, admin_headers):
    response = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "new@example.org",
            "password": "route-pass-123",
            "full_name": "New Person",
            "role": "dispatcher",
        },
    )
    assert response.status_code == 201
    assert response.json()["role"] == "dispatcher"


def test_creating_duplicate_email_conflicts(client, admin_headers):
    payload = {
        "email": "dup@example.org",
        "password": "route-pass-123",
        "full_name": "Dup",
        "role": "driver",
    }
    first = client.post("/users", headers=admin_headers, json=payload)
    assert first.status_code == 201
    second = client.post("/users", headers=admin_headers, json=payload)
    assert second.status_code == 409


def test_only_admin_can_create_school(client, db_session):
    make_user(db_session, email="dispatch@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatch@example.org")
    response = client.post(
        "/schools",
        headers=auth_headers(token),
        json={"name": "Test ES", "location_lat": 29.7, "location_lon": -95.4},
    )
    assert response.status_code == 403


def test_any_authenticated_role_can_list_schools(client, admin_headers, db_session):
    client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Test ES", "location_lat": 29.7, "location_lon": -95.4},
    )
    make_user(db_session, email="driver@example.org", role=Role.DRIVER)
    from tests.conftest import login as _login

    token = _login(client, email="driver@example.org")
    response = client.get("/schools", headers=auth_headers(token))
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_vehicle_creation_rejects_unknown_qualification_code(client, admin_headers):
    response = client.post(
        "/vehicles",
        headers=admin_headers,
        json={"label": "Bus 1", "qualification_codes": ["not-a-real-code"]},
    )
    assert response.status_code == 400


def test_vehicle_creation_with_valid_qualification_code(client, admin_headers):
    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": "wheelchair", "kind": "vehicle_capability", "description": "Wheelchair lift"},
    )
    response = client.post(
        "/vehicles",
        headers=admin_headers,
        json={
            "label": "Bus 1",
            "nominal_capacity": 48,
            "effective_capacity": 44,
            "qualification_codes": ["wheelchair"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["nominal_capacity"] == 48
    assert body["qualifications"][0]["code"] == "wheelchair"


def test_vehicle_rejects_effective_capacity_le_zero(client, admin_headers):
    response = client.post(
        "/vehicles", headers=admin_headers, json={"label": "Bus 1", "effective_capacity": 0}
    )
    assert response.status_code == 422  # pydantic validation, gt=0


def test_vehicle_dimension_fields_round_trip(client, admin_headers):
    """A field accepted by VehicleCreate must actually reach the DB and
    come back in the response, not just pass schema validation — the
    Phase 5 student_id bug (REBOOT.md gotcha #7) silently dropped a
    field at exactly this router-constructor-kwargs step while every
    schema-level check kept passing."""
    response = client.post(
        "/vehicles",
        headers=admin_headers,
        json={
            "label": "Bus 1",
            "length_m": 10.5,
            "width_m": 2.5,
            "height_m": 3.2,
            "weight_kg": 12000.0,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["length_m"] == 10.5
    assert body["width_m"] == 2.5
    assert body["height_m"] == 3.2
    assert body["weight_kg"] == 12000.0

    listed = client.get("/vehicles", headers=admin_headers).json()
    created = next(v for v in listed if v["id"] == body["id"])
    assert created["length_m"] == 10.5


def test_vehicle_dimension_fields_are_optional(client, admin_headers):
    response = client.post("/vehicles", headers=admin_headers, json={"label": "Bus 1"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["length_m"] is None
    assert body["width_m"] is None
    assert body["height_m"] is None
    assert body["weight_kg"] is None


def test_vehicle_rejects_non_positive_dimension(client, admin_headers):
    response = client.post(
        "/vehicles", headers=admin_headers, json={"label": "Bus 1", "height_m": 0}
    )
    assert response.status_code == 422


def test_school_admin_sees_only_own_school_runs(client, admin_headers, db_session):
    s1 = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "ES A", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    s2 = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "ES B", "location_lat": 29.71, "location_lon": -95.41},
    ).json()

    for school in (s1, s2):
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
            },
        )

    make_user(db_session, email="admin-a@example.org", role=Role.SCHOOL_ADMIN, school_id=s1["id"])
    token = login(client, email="admin-a@example.org")
    response = client.get(
        "/runs", headers=auth_headers(token), params={"service_date": "2026-09-01"}
    )
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 1
    assert runs[0]["school_id"] == s1["id"]


def test_school_admin_without_school_link_is_forbidden(client, db_session, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "ES A", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
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
        },
    )
    make_user(db_session, email="unlinked@example.org", role=Role.SCHOOL_ADMIN)  # no school_id
    token = login(client, email="unlinked@example.org")
    response = client.get(
        "/runs", headers=auth_headers(token), params={"service_date": "2026-09-01"}
    )
    assert response.status_code == 403


def test_driver_role_cannot_list_runs(client, db_session, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "ES A", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
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
        },
    )
    make_user(db_session, email="driver@example.org", role=Role.DRIVER)
    token = login(client, email="driver@example.org")
    response = client.get(
        "/runs", headers=auth_headers(token), params={"service_date": "2026-09-01"}
    )
    assert response.status_code == 403
