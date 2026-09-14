"""Ridership -> passenger_count decision support: PATCH /runs/{id} and
GET /runs/{id}/expected-riders. Deliberately NOT spec section 4.3's
stop-sequence route shortening (this system has no Route/stop-sequence
model) -- see docs/domain-model.md and the PR this shipped in for the
scope boundary."""

from isd_api.models import AuditLogEntry, Role
from tests.conftest import auth_headers, login, make_user


def _seed_school(client, admin_headers):
    return client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "Riverside Elementary", "location_lat": 29.70, "location_lon": -95.40},
    ).json()


def _seed_run(client, admin_headers, *, school_id, direction="am", service_date="2026-09-01"):
    return client.post(
        "/runs",
        headers=admin_headers,
        json={
            "service_date": service_date,
            "school_id": school_id,
            "direction": direction,
            "window_earliest": 360,
            "window_latest": 420,
            "duration_minutes": 40,
            "buffer_minutes": 10,
        },
    ).json()


def test_run_direction_round_trips(client, admin_headers):
    """The exact class of bug gotcha #7 warns about: assert the field
    actually reaches the response, not just that schema validation
    accepts it."""
    school = _seed_school(client, admin_headers)
    run = _seed_run(client, admin_headers, school_id=school["id"], direction="pm")
    assert run["direction"] == "pm"

    listed = client.get(
        "/runs", headers=admin_headers, params={"service_date": "2026-09-01"}
    ).json()
    created = next(r for r in listed if r["id"] == run["id"])
    assert created["direction"] == "pm"


def test_update_run_updates_passenger_count_and_audits(client, admin_headers, db_session):
    school = _seed_school(client, admin_headers)
    run = _seed_run(client, admin_headers, school_id=school["id"])

    response = client.patch(
        f"/runs/{run['id']}", headers=admin_headers, json={"passenger_count": 12}
    )
    assert response.status_code == 200, response.text
    assert response.json()["passenger_count"] == 12

    entries = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "run", AuditLogEntry.action == "updated")
        .all()
    )
    assert len(entries) == 1
    assert entries[0].before_state == {"passenger_count": 0}
    assert entries[0].after_state == {"passenger_count": 12}
    assert entries[0].actor_user_id is not None


def test_update_run_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    school = _seed_school(client, admin_headers)
    run = _seed_run(client, admin_headers, school_id=school["id"])

    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.patch(
        f"/runs/{run['id']}", headers=auth_headers(token), json={"passenger_count": 5}
    )
    assert response.status_code == 403


def test_update_run_rejects_unknown_run(client, admin_headers):
    response = client.patch("/runs/999", headers=admin_headers, json={"passenger_count": 5})
    assert response.status_code == 404


def test_expected_riders_counts_default_and_override_riders(client, admin_headers):
    school = _seed_school(client, admin_headers)
    run = _seed_run(client, admin_headers, school_id=school["id"], direction="am")

    client.post(
        "/students",
        headers=admin_headers,
        json={"full_name": "Riding Default", "school_id": school["id"]},
    )
    not_riding_default = client.post(
        "/students",
        headers=admin_headers,
        json={
            "full_name": "Not Riding Default",
            "school_id": school["id"],
            "default_ridership": "does_not_ride",
        },
    ).json()
    # Override flips the not-riding-by-default student to riding for
    # this exact leg (spec section 4.5's "late request to ride").
    client.patch(
        f"/students/{not_riding_default['id']}/ridership",
        headers=admin_headers,
        json={"service_date": "2026-09-01", "direction": "am", "is_riding": True},
    )
    # A third student overridden OUT for this leg should not be counted.
    riding_but_overridden_out = client.post(
        "/students",
        headers=admin_headers,
        json={"full_name": "Overridden Out", "school_id": school["id"]},
    ).json()
    client.patch(
        f"/students/{riding_but_overridden_out['id']}/ridership",
        headers=admin_headers,
        json={"service_date": "2026-09-01", "direction": "am", "is_riding": False},
    )

    response = client.get(f"/runs/{run['id']}/expected-riders", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expected_passenger_count"] == 2
    assert set(body["riding_student_names"]) == {"Riding Default", "Not Riding Default"}
    assert body["ambiguous"] is False


def test_expected_riders_ignores_a_different_directions_override(client, admin_headers):
    school = _seed_school(client, admin_headers)
    run = _seed_run(client, admin_headers, school_id=school["id"], direction="am")
    student = client.post(
        "/students",
        headers=admin_headers,
        json={
            "full_name": "PM Only",
            "school_id": school["id"],
            "default_ridership": "does_not_ride",
        },
    ).json()
    # Rides PM, not AM -- must not count toward this AM run.
    client.patch(
        f"/students/{student['id']}/ridership",
        headers=admin_headers,
        json={"service_date": "2026-09-01", "direction": "pm", "is_riding": True},
    )

    response = client.get(f"/runs/{run['id']}/expected-riders", headers=admin_headers)
    assert response.json()["expected_passenger_count"] == 0


def test_expected_riders_flags_ambiguous_when_multiple_runs_share_school_date_direction(
    client, admin_headers
):
    school = _seed_school(client, admin_headers)
    run_a = _seed_run(client, admin_headers, school_id=school["id"], direction="am")
    _seed_run(client, admin_headers, school_id=school["id"], direction="am")  # second bus

    response = client.get(f"/runs/{run_a['id']}/expected-riders", headers=admin_headers)
    assert response.json()["ambiguous"] is True


def test_expected_riders_not_ambiguous_when_the_other_run_is_a_different_direction(
    client, admin_headers
):
    school = _seed_school(client, admin_headers)
    run_am = _seed_run(client, admin_headers, school_id=school["id"], direction="am")
    _seed_run(client, admin_headers, school_id=school["id"], direction="pm")

    response = client.get(f"/runs/{run_am['id']}/expected-riders", headers=admin_headers)
    assert response.json()["ambiguous"] is False


def test_expected_riders_requires_admin_or_dispatcher_role(client, admin_headers, db_session):
    school = _seed_school(client, admin_headers)
    run = _seed_run(client, admin_headers, school_id=school["id"])

    make_user(db_session, email="schooladmin@example.org", role=Role.SCHOOL_ADMIN)
    token = login(client, email="schooladmin@example.org")
    response = client.get(f"/runs/{run['id']}/expected-riders", headers=auth_headers(token))
    assert response.status_code == 403


def test_expected_riders_rejects_unknown_run(client, admin_headers):
    response = client.get("/runs/999/expected-riders", headers=admin_headers)
    assert response.status_code == 404
