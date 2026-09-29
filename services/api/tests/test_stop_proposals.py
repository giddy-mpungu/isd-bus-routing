"""Proposing stops from students' homes (spec section 3.1), and the
approve / reject / relocate workflow."""

import math

import pytest

from isd_api import eligibility
from isd_api.models import AuditLogEntry, Role
from isd_api.stop_proposals import Hazard, Home, Place, propose
from tests.conftest import auth_headers, login, make_user

# Degrees of latitude in a mile (the sphere eligibility.py uses), and of
# longitude at 29.7 degrees north.
MILE = math.degrees(eligibility.METRES_PER_MILE / 6_371_000)
MILE_E = MILE / math.cos(math.radians(29.7))

BASE_LAT, BASE_LON = 29.7 + 3 * MILE, -95.4  # 3 mi north of the school


def at(north_mi=0.0, east_mi=0.0):
    return BASE_LAT + north_mi * MILE, BASE_LON + east_mi * MILE_E


def home(sid, north_mi=0.0, east_mi=0.0, limit=0.25, specialized=False):
    lat, lon = at(north_mi, east_mi)
    return Home(sid, lat, lon, limit, specialized)


# --- The algorithm -----------------------------------------------------------


def test_neighbours_share_one_stop_at_their_centre():
    [stop] = propose([home(1), home(2, east_mi=0.1)], [], min_spacing_miles=0.1)
    assert (stop.kind, stop.student_ids, stop.label) == ("new", [1, 2], "Proposed stop 1")
    assert (stop.lat, stop.lon) == pytest.approx(at(east_mi=0.05))


def test_homes_too_far_apart_get_their_own_stops():
    stops = propose([home(1), home(2, east_mi=1.0)], [], min_spacing_miles=0.1)
    assert sorted(s.student_ids for s in stops) == [[1], [2]]
    assert [s.label for s in stops] == ["Proposed stop 1", "Proposed stop 2"]


def test_an_existing_stop_in_walking_distance_is_reused():
    lat, lon = at(north_mi=0.2)
    existing = Place(9, "Oak & 5th", lat, lon)
    [stop] = propose([home(1)], [existing], min_spacing_miles=0.1)
    assert (stop.kind, stop.stop_id, stop.label, stop.student_ids) == (
        "existing",
        9,
        "Oak & 5th",
        [1],
    )


def test_the_nearest_existing_stop_wins():
    near = Place(8, "Near", *at(north_mi=0.1))
    far = Place(9, "Far", *at(north_mi=-0.2))
    [stop] = propose([home(1)], [far, near], min_spacing_miles=0.1)
    assert stop.stop_id == 8


def test_specialized_transportation_gets_a_curb_stop_at_home():
    stops = propose(
        [home(1, specialized=True, limit=0.0), home(2, east_mi=0.05)],
        [Place(9, "Nearby", *at(east_mi=0.02))],
        min_spacing_miles=0.1,
    )
    curb = next(s for s in stops if s.kind == "curb")
    assert (curb.student_ids, curb.label, (curb.lat, curb.lon)) == ([1], "Curb stop 1", at())
    assert next(s for s in stops if s.kind == "existing").student_ids == [2]


def test_a_lopsided_group_stops_at_a_home_rather_than_an_unreachable_centre():
    # Four homes just east, one just west: the centre sits east, too far
    # for the western student, so the stop goes at the home everyone can reach.
    homes = [home(1), home(2, east_mi=-0.24)] + [home(i, east_mi=0.24) for i in (3, 4, 5, 6)]
    [stop] = propose(homes, [], min_spacing_miles=0.1)
    assert sorted(stop.student_ids) == [1, 2, 3, 4, 5, 6]
    assert (stop.lat, stop.lon) == pytest.approx(at())


def test_a_stop_closer_than_the_minimum_spacing_is_flagged():
    existing = Place(9, "Oak & 5th", *at(north_mi=0.3))
    [stop] = propose([home(1)], [existing], min_spacing_miles=0.5)
    assert stop.kind == "new"
    assert stop.warnings == ["0.30 mi from Oak & 5th (the district's minimum spacing is 0.5 mi)"]


def test_two_new_stops_too_close_together_are_flagged():
    stops = propose([home(1), home(2, east_mi=0.3)], [], min_spacing_miles=0.35)
    assert len(stops) == 2
    assert stops[1].warnings == [
        "0.30 mi from another proposed stop (the district's minimum spacing is 0.35 mi)"
    ]


def test_a_school_sized_roster_is_quick():
    import time

    homes = [
        home(i, north_mi=((i * 37) % 97) / 20, east_mi=((i * 53) % 89) / 20) for i in range(400)
    ]
    started = time.perf_counter()
    stops = propose(homes, [], min_spacing_miles=0.1)
    assert time.perf_counter() - started < 5
    assert sorted(i for s in stops for i in s.student_ids) == list(range(400))
    # Every student can walk to their stop.
    by_id = {h.student_id: h for h in homes}
    for s in stops:
        for i in s.student_ids:
            walk = eligibility.miles_between(by_id[i].lat, by_id[i].lon, s.lat, s.lon)
            assert walk <= 0.25 + 1e-9


def test_a_stop_near_a_reported_hazard_is_flagged():
    flood = Hazard("frequent_flooding", "Low water crossing", *at(east_mi=0.05))
    turn = Hazard("preferred_entrance", "Not a hazard", *at())
    [stop] = propose([home(1)], [], min_spacing_miles=0.1, hazards=[flood, turn])
    assert stop.warnings == ["0.05 mi from frequent flooding: Low water crossing"]


def test_proposals_are_the_same_every_time():
    homes = [home(i, north_mi=(i % 5) * 0.2, east_mi=(i // 5) * 0.2) for i in range(1, 21)]
    first = [(p.student_ids, p.lat, p.lon) for p in propose(homes, [], min_spacing_miles=0.1)]
    again = [
        (p.student_ids, p.lat, p.lon)
        for p in propose(list(reversed(homes)), [], min_spacing_miles=0.1)
    ]
    assert first == again
    assert sorted(i for ids, _, _ in first for i in ids) == list(range(1, 21))


# --- The workflow ------------------------------------------------------------


def _school(client, h):
    return client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()


def _student_at(client, h, school, name, north_mi=0.0, east_mi=0.0, **fields):
    student = client.post(
        "/students",
        headers=h,
        json={"full_name": name, "school_id": school["id"], "grade": "4", **fields},
    ).json()
    lat, lon = at(north_mi, east_mi)
    client.put(
        f"/students/{student['id']}/home",
        headers=h,
        json={"address": f"{name}'s house", "location_lat": lat, "location_lon": lon},
    )
    return student


def _generate(client, h, school):
    return client.post("/stop-proposals/generate", headers=h, json={"school_id": school["id"]})


def test_generating_proposes_stops_for_eligible_students_without_one(client, admin_headers):
    school = _school(client, admin_headers)
    _student_at(client, admin_headers, school, "Ana")
    _student_at(client, admin_headers, school, "Ben", east_mi=0.1)
    _student_at(client, admin_headers, school, "Cy", east_mi=1.0)
    # Left out: no home, close to school, already has a stop.
    client.post(
        "/students", headers=admin_headers, json={"full_name": "Dee", "school_id": school["id"]}
    )
    near = client.post(
        "/students", headers=admin_headers, json={"full_name": "Eve", "school_id": school["id"]}
    ).json()
    client.put(
        f"/students/{near['id']}/home",
        headers=admin_headers,
        json={"address": "near", "location_lat": 29.701, "location_lon": -95.4},
    )
    stop = client.post(
        "/stops",
        headers=admin_headers,
        json={"label": "Far away", "location_lat": 31, "location_lon": -97},
    ).json()
    fay = _student_at(client, admin_headers, school, "Fay", east_mi=3.0)
    client.patch(f"/students/{fay['id']}", headers=admin_headers, json={"stop_id": stop["id"]})

    response = _generate(client, admin_headers, school)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["students_considered"],
        body["no_home"],
        body["not_eligible"],
        body["already_have_stop"],
    ) == (3, 1, 1, 1)
    groups = sorted(
        (sorted(r["full_name"] for r in p["riders"]), p["kind"]) for p in body["proposals"]
    )
    assert groups == [(["Ana", "Ben"], "new"), (["Cy"], "new")]
    pair = next(p for p in body["proposals"] if len(p["riders"]) == 2)
    assert all(r["walk_miles"] == pytest.approx(0.05, abs=0.01) for r in pair["riders"])
    assert all(r["walk_limit_miles"] == 0.25 for r in pair["riders"])
    assert pair["warnings"] == []
    # Stop labels are seen by drivers and families: never a student's name.
    assert all("Ana" not in p["label"] and "Cy" not in p["label"] for p in body["proposals"])


def test_proposals_are_for_transportation_admins_only(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    make_user(db_session, email="d@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="d@example.org"))
    assert _generate(client, dispatcher, school).status_code == 403
    assert (
        client.get("/stop-proposals", headers=dispatcher, params={"school_id": school["id"]})
    ).status_code == 403


def test_approving_creates_the_stop_and_assigns_its_students(client, admin_headers, db_session):
    school = _school(client, admin_headers)
    ana = _student_at(client, admin_headers, school, "Ana")
    ben = _student_at(client, admin_headers, school, "Ben", east_mi=0.1)
    [proposal] = _generate(client, admin_headers, school).json()["proposals"]

    approved = client.post(f"/stop-proposals/{proposal['id']}/approve", headers=admin_headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    stop_id = approved.json()["stop_id"]
    stops = {s["id"]: s for s in client.get("/stops", headers=admin_headers).json()}
    assert stops[stop_id]["label"] == "Proposed stop 1"
    students = {s["id"]: s for s in client.get("/students", headers=admin_headers).json()}
    assert students[ana["id"]]["stop_id"] == stop_id == students[ben["id"]]["stop_id"]

    again = client.post(f"/stop-proposals/{proposal['id']}/approve", headers=admin_headers)
    assert again.status_code == 409
    actions = {
        e.action
        for e in db_session.query(AuditLogEntry).filter(
            AuditLogEntry.entity_type.in_(["stop", "stop_proposal", "stop_proposals"])
        )
    }
    assert {"generated", "created", "approved"} <= actions


def test_approving_an_existing_stop_proposal_just_assigns_it(client, admin_headers):
    school = _school(client, admin_headers)
    lat, lon = at(north_mi=0.1)
    oak = client.post(
        "/stops",
        headers=admin_headers,
        json={"label": "Oak & 5th", "location_lat": lat, "location_lon": lon},
    ).json()
    ana = _student_at(client, admin_headers, school, "Ana")
    [proposal] = _generate(client, admin_headers, school).json()["proposals"]
    assert (proposal["kind"], proposal["stop_id"]) == ("existing", oak["id"])
    client.post(f"/stop-proposals/{proposal['id']}/approve", headers=admin_headers)
    assert len(client.get("/stops", headers=admin_headers).json()) == 1
    [student] = [
        s for s in client.get("/students", headers=admin_headers).json() if s["id"] == ana["id"]
    ]
    assert student["stop_id"] == oak["id"]
    moved = client.patch(
        f"/stop-proposals/{proposal['id']}",
        headers=admin_headers,
        json={"location_lat": 1, "location_lon": 1},
    )
    assert moved.status_code == 409


def test_relocating_a_proposal_rechecks_the_walks(client, admin_headers):
    school = _school(client, admin_headers)
    _student_at(client, admin_headers, school, "Ana")
    [proposal] = _generate(client, admin_headers, school).json()["proposals"]
    lat, lon = at(north_mi=0.4)
    moved = client.patch(
        f"/stop-proposals/{proposal['id']}",
        headers=admin_headers,
        json={"location_lat": lat, "location_lon": lon, "label": "Elm & 2nd"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["label"] == "Elm & 2nd"
    assert moved.json()["warnings"] == ["Ana would walk 0.40 mi (limit 0.25 mi)"]
    half = client.patch(
        f"/stop-proposals/{proposal['id']}", headers=admin_headers, json={"location_lat": 1}
    )
    assert half.status_code == 422


def test_rejecting_and_regenerating_keeps_decisions_as_history(client, admin_headers):
    school = _school(client, admin_headers)
    _student_at(client, admin_headers, school, "Ana")
    _student_at(client, admin_headers, school, "Cy", east_mi=1.0)
    first = _generate(client, admin_headers, school).json()["proposals"]
    rejected = client.post(f"/stop-proposals/{first[0]['id']}/reject", headers=admin_headers)
    assert rejected.json()["status"] == "rejected"

    _generate(client, admin_headers, school)
    listed = client.get(
        "/stop-proposals", headers=admin_headers, params={"school_id": school["id"]}
    ).json()
    assert [p["status"] for p in listed].count("rejected") == 1
    assert [p["status"] for p in listed].count("pending") == 2
    # Pending ones come first.
    assert listed[-1]["status"] == "rejected"


def test_the_minimum_spacing_is_a_district_setting(client, admin_headers):
    rules = client.get("/transportation-rules", headers=admin_headers).json()
    assert rules["min_stop_spacing_miles"] == 0.1
    body = {k: rules[k] for k in ("eligibility_miles", "walk_miles", "ride_minutes")}
    updated = client.put(
        "/transportation-rules",
        headers=admin_headers,
        json={**body, "min_stop_spacing_miles": 0.2},
    ).json()
    assert updated["min_stop_spacing_miles"] == 0.2
    # Left out, it stays as it was.
    again = client.put("/transportation-rules", headers=admin_headers, json=body).json()
    assert again["min_stop_spacing_miles"] == 0.2
