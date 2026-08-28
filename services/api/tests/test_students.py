"""Phase 5 MVP: Student/Stop entities, guardian linking, and ridership
declarations (spec sections 3, 4)."""

from isd_api.models import Role
from tests.conftest import auth_headers, login, make_user


def _seed_family(client, admin_headers, *, default_ridership="rides"):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside Elementary", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    stop = client.post(
        "/stops",
        headers=admin_headers,
        json={"label": "Oak & 5th", "location_lat": 29.71, "location_lon": -95.41},
    ).json()
    student = client.post(
        "/students",
        headers=admin_headers,
        json={
            "full_name": "Jamie Student",
            "school_id": school["id"],
            "stop_id": stop["id"],
            "default_ridership": default_ridership,
        },
    ).json()
    return school, stop, student


def _make_parent(db_session, client, *, email="parent@example.org"):
    make_user(db_session, email=email, role=Role.PARENT)
    token = login(client, email=email)
    return auth_headers(token)


def test_admin_can_create_and_list_students(client, admin_headers):
    _school, _stop, student = _seed_family(client, admin_headers)
    response = client.get("/students", headers=admin_headers)
    assert response.status_code == 200
    assert student["id"] in [s["id"] for s in response.json()]


def test_creating_a_student_requires_admin_role(client, admin_headers, db_session):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "S", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    make_user(db_session, email="dispatcher2@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher2@example.org")
    response = client.post(
        "/students",
        headers=auth_headers(token),
        json={"full_name": "Jamie Student", "school_id": school["id"]},
    )
    assert response.status_code == 403


def test_linking_a_guardian_requires_parent_role_user(client, admin_headers, db_session):
    _school, _stop, student = _seed_family(client, admin_headers)
    make_user(db_session, email="dispatcher3@example.org", role=Role.DISPATCHER)
    from isd_api.models import User

    non_parent = db_session.query(User).filter(User.email == "dispatcher3@example.org").one()
    response = client.post(
        f"/students/{student['id']}/guardians",
        headers=admin_headers,
        json={"user_id": non_parent.id},
    )
    assert response.status_code == 400


def test_linked_parent_sees_child_in_my_family(client, admin_headers, db_session):
    school, stop, student = _seed_family(client, admin_headers)
    parent_headers = _make_parent(db_session, client)
    from isd_api.models import User

    parent = db_session.query(User).filter(User.email == "parent@example.org").one()
    link = client.post(
        f"/students/{student['id']}/guardians",
        headers=admin_headers,
        json={"user_id": parent.id},
    )
    assert link.status_code == 204

    response = client.get(
        "/students/my-family", headers=parent_headers, params={"service_date": "2026-09-01"}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["student_id"] == student["id"]
    assert body[0]["full_name"] == "Jamie Student"
    assert body[0]["school_name"] == school["name"]
    assert body[0]["stop_label"] == stop["label"]
    assert body[0]["riding_am"] is True
    assert body[0]["riding_pm"] is True


def test_unlinked_parent_sees_no_family_data(client, admin_headers, db_session):
    _school, _stop, _student = _seed_family(client, admin_headers)
    parent_headers = _make_parent(db_session, client, email="stranger@example.org")

    response = client.get(
        "/students/my-family", headers=parent_headers, params={"service_date": "2026-09-01"}
    )
    assert response.status_code == 200
    assert response.json() == []


def test_default_does_not_ride_reflected_until_overridden(client, admin_headers, db_session):
    _school, _stop, student = _seed_family(client, admin_headers, default_ridership="does_not_ride")
    parent_headers = _make_parent(db_session, client)
    from isd_api.models import User

    parent = db_session.query(User).filter(User.email == "parent@example.org").one()
    client.post(
        f"/students/{student['id']}/guardians", headers=admin_headers, json={"user_id": parent.id}
    )

    response = client.get(
        "/students/my-family", headers=parent_headers, params={"service_date": "2026-09-01"}
    )
    body = response.json()[0]
    assert body["riding_am"] is False
    assert body["riding_pm"] is False


def test_parent_can_override_am_leg_without_touching_pm(client, admin_headers, db_session):
    """spec section 4.2: 'A student may therefore ride to school but
    not home, or vice versa' — AM and PM are independent legs."""
    _school, _stop, student = _seed_family(client, admin_headers)
    parent_headers = _make_parent(db_session, client)
    from isd_api.models import User

    parent = db_session.query(User).filter(User.email == "parent@example.org").one()
    client.post(
        f"/students/{student['id']}/guardians", headers=admin_headers, json={"user_id": parent.id}
    )

    override = client.patch(
        f"/students/{student['id']}/ridership",
        headers=parent_headers,
        json={"service_date": "2026-09-01", "direction": "am", "is_riding": False},
    )
    assert override.status_code == 204

    response = client.get(
        "/students/my-family", headers=parent_headers, params={"service_date": "2026-09-01"}
    )
    body = response.json()[0]
    assert body["riding_am"] is False
    assert body["riding_pm"] is True  # unaffected, still the default


def test_redeclaring_the_same_leg_updates_rather_than_duplicates(client, admin_headers, db_session):
    _school, _stop, student = _seed_family(client, admin_headers)
    parent_headers = _make_parent(db_session, client)
    from isd_api.models import RidershipOverride, User

    parent = db_session.query(User).filter(User.email == "parent@example.org").one()
    client.post(
        f"/students/{student['id']}/guardians", headers=admin_headers, json={"user_id": parent.id}
    )

    client.patch(
        f"/students/{student['id']}/ridership",
        headers=parent_headers,
        json={"service_date": "2026-09-01", "direction": "am", "is_riding": False},
    )
    client.patch(
        f"/students/{student['id']}/ridership",
        headers=parent_headers,
        json={"service_date": "2026-09-01", "direction": "am", "is_riding": True},
    )

    rows = db_session.query(RidershipOverride).filter_by(student_id=student["id"]).all()
    assert len(rows) == 1
    assert rows[0].is_riding is True


def test_student_can_only_declare_ridership_for_self(client, admin_headers, db_session):
    _school, _stop, student = _seed_family(client, admin_headers)
    _school2, _stop2, other_student = _seed_family(client, admin_headers)

    make_user(db_session, email="student1@example.org", role=Role.STUDENT, student_id=student["id"])
    token = login(client, email="student1@example.org")

    own = client.patch(
        f"/students/{student['id']}/ridership",
        headers=auth_headers(token),
        json={"service_date": "2026-09-01", "direction": "am", "is_riding": False},
    )
    assert own.status_code == 204

    other = client.patch(
        f"/students/{other_student['id']}/ridership",
        headers=auth_headers(token),
        json={"service_date": "2026-09-01", "direction": "am", "is_riding": False},
    )
    assert other.status_code == 403


def test_admin_can_declare_ridership_for_any_student(client, admin_headers):
    """Covers a phone-in request from a family without an account."""
    _school, _stop, student = _seed_family(client, admin_headers)
    response = client.patch(
        f"/students/{student['id']}/ridership",
        headers=admin_headers,
        json={"service_date": "2026-09-01", "direction": "pm", "is_riding": False},
    )
    assert response.status_code == 204


def test_creating_a_user_links_the_student_id(client, admin_headers):
    """Regression: POST /users must actually persist student_id, the
    same way it already did for driver_id/school_id — caught by
    manual testing, not by any automated test, when the field was
    accepted by the schema but silently dropped before hitting the
    ORM constructor."""
    _school, _stop, student = _seed_family(client, admin_headers)
    response = client.post(
        "/users",
        headers=admin_headers,
        json={
            "email": "student1@example.org",
            "password": "studentpass123",
            "full_name": "Jamie Student",
            "role": "student",
            "student_id": student["id"],
        },
    )
    assert response.status_code == 201
    assert response.json()["student_id"] == student["id"]


def test_dispatcher_cannot_access_my_family_endpoint(client, admin_headers, db_session):
    _seed_family(client, admin_headers)
    make_user(db_session, email="dispatcher4@example.org", role=Role.DISPATCHER)
    token = login(client, email="dispatcher4@example.org")
    response = client.get(
        "/students/my-family", headers=auth_headers(token), params={"service_date": "2026-09-01"}
    )
    assert response.status_code == 403
