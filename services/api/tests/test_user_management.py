"""User management (spec section 17 "user permissions"): PATCH /users/{id}
for role reassignment, driver/school/student relinking, and deactivation.
Previously POST/GET /users existed with no way to edit or deactivate an
account at all."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _create_user(client, admin_headers, **overrides):
    payload = {
        "email": "new@example.org",
        "password": "route-pass-123",
        "full_name": "New Person",
        "role": "dispatcher",
    }
    payload.update(overrides)
    return client.post("/users", headers=admin_headers, json=payload).json()


def test_update_user_changes_role_and_audits(client, admin_headers, db_session):
    user = _create_user(client, admin_headers, role="dispatcher")
    response = client.patch(
        f"/users/{user['id']}", headers=admin_headers, json={"role": "transportation_admin"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "transportation_admin"

    entry = db_session.query(AuditLogEntry).filter_by(entity_type="user", action="updated").one()
    assert entry.before_state["role"] == "dispatcher"
    assert entry.after_state["role"] == "transportation_admin"


def test_deactivating_a_user_blocks_them_immediately(client, admin_headers):
    user = _create_user(client, admin_headers, email="deactivate-me@example.org")
    token = login(client, email="deactivate-me@example.org", password="route-pass-123")
    assert client.get("/users/me", headers=auth_headers(token)).status_code == 200

    deactivated = client.patch(
        f"/users/{user['id']}", headers=admin_headers, json={"is_active": False}
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    # The already-issued token stops working on its very next use --
    # get_current_user checks User.is_active on every request.
    assert client.get("/users/me", headers=auth_headers(token)).status_code == 401


def test_reactivating_a_user_restores_access(client, admin_headers):
    user = _create_user(client, admin_headers, email="restore-me@example.org")
    client.patch(f"/users/{user['id']}", headers=admin_headers, json={"is_active": False})
    reactivated = client.patch(
        f"/users/{user['id']}", headers=admin_headers, json={"is_active": True}
    )
    assert reactivated.json()["is_active"] is True
    token = login(client, email="restore-me@example.org", password="route-pass-123")
    assert client.get("/users/me", headers=auth_headers(token)).status_code == 200


def test_admin_cannot_deactivate_their_own_account(client, admin_headers, db_session):
    me = client.get("/users/me", headers=admin_headers).json()
    response = client.patch(f"/users/{me['id']}", headers=admin_headers, json={"is_active": False})
    assert response.status_code == 400
    assert client.get("/users/me", headers=admin_headers).status_code == 200


def test_relinking_driver_school_student_validates_existence(client, admin_headers):
    user = _create_user(client, admin_headers, role="driver")
    response = client.patch(
        f"/users/{user['id']}", headers=admin_headers, json={"driver_id": 999999}
    )
    assert response.status_code == 400


def test_relinking_to_an_already_linked_driver_conflicts(client, admin_headers):
    driver = client.post(
        "/drivers", headers=admin_headers, json={"license_class": "cdl_a", "full_name": "Driver A"}
    ).json()
    first = _create_user(
        client, admin_headers, email="first@example.org", role="driver", driver_id=driver["id"]
    )
    second = _create_user(client, admin_headers, email="second@example.org", role="driver")

    response = client.patch(
        f"/users/{second['id']}", headers=admin_headers, json={"driver_id": driver["id"]}
    )
    assert response.status_code == 409
    # The first user's link is untouched.
    refreshed_first = next(
        u for u in client.get("/users", headers=admin_headers).json() if u["id"] == first["id"]
    )
    assert refreshed_first["driver_id"] == driver["id"]


def test_relinking_school_and_student(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside Elementary", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    other_school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Lakeside", "location_lat": 1, "location_lon": 1},
    ).json()
    admin_user = _create_user(
        client,
        admin_headers,
        email="admin2@example.org",
        role="school_admin",
        school_id=school["id"],
    )
    assert admin_user["school_id"] == school["id"]

    moved = client.patch(
        f"/users/{admin_user['id']}", headers=admin_headers, json={"school_id": other_school["id"]}
    )
    assert moved.json()["school_id"] == other_school["id"]


def test_update_user_not_found(client, admin_headers):
    response = client.patch("/users/999999", headers=admin_headers, json={"is_active": False})
    assert response.status_code == 404


def test_only_transportation_admin_can_update_a_user(client, admin_headers, db_session):
    target = _create_user(client, admin_headers, email="target@example.org")
    make_user(db_session, email="disp@example.org", role=Role.DISPATCHER)
    headers = auth_headers(login(client, email="disp@example.org"))
    response = client.patch(f"/users/{target['id']}", headers=headers, json={"is_active": False})
    assert response.status_code == 403


def test_create_user_validates_driver_school_student_ids(client, admin_headers):
    bad_driver = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "a@example.org",
            "password": "route-pass-123",
            "full_name": "A",
            "role": "driver",
            "driver_id": 999999,
        },
    )
    assert bad_driver.status_code == 400


def test_user_read_includes_created_at(client, admin_headers):
    user = _create_user(client, admin_headers, email="timestamped@example.org")
    assert user["created_at"] is not None
