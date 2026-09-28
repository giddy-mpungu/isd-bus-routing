"""Student grade, eligibility, accommodations and home location (spec
sections 3, 3.1), with the US Census geocoder and district transportation
rules. The school sits at (29.7, -95.4)."""

import math
import re

import pytest

from isd_api import eligibility
from isd_api.integrations import census_geocoder
from isd_api.models import AuditLogEntry, Role, Student
from tests.conftest import auth_headers, login, make_user
from tests.test_sis_import import _import, _school

# Degrees of latitude in a mile, on the same sphere eligibility.py uses.
MILE = math.degrees(eligibility.METRES_PER_MILE / 6_371_000)


def _census_hit(lat, lon, matched="123 MAIN ST, HOUSTON, TX, 77002"):
    return {
        "result": {
            "addressMatches": [{"matchedAddress": matched, "coordinates": {"x": lon, "y": lat}}]
        }
    }


@pytest.fixture()
def census(monkeypatch):
    """Stands in for the Census service; records every URL requested."""
    calls: list[str] = []
    state = {"payload": _census_hit(29.7 + 2.5 * MILE, -95.4)}

    def fake_fetch(url):
        calls.append(url)
        if state["payload"] == "down":
            raise census_geocoder.GeocoderUnavailable("timed out")
        return state["payload"]

    monkeypatch.setattr(census_geocoder, "_fetch_json", fake_fetch)
    return {"calls": calls, "state": state}


def _student(client, h, **fields):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    body = {"full_name": "Ana Lopez", "school_id": school["id"], **fields}
    response = client.post("/students", headers=h, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _set_home(client, h, student, **body):
    return client.put(
        f"/students/{student['id']}/home",
        headers=h,
        json={"address": "123 Main St, Houston, TX 77002", **body},
    )


def _listed(client, h, student):
    return next(s for s in client.get("/students", headers=h).json() if s["id"] == student["id"])


# --- Grades and bands --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "grade"),
    [
        ("PK", "PK"),
        ("TK", "PK"),
        ("kg", "K"),
        ("K", "K"),
        ("01", "1"),
        ("3rd", "3"),
        ("12", "12"),
        ("13", None),
        ("UG", None),
        ("", None),
    ],
)
def test_grades_are_normalised(raw, grade):
    assert eligibility.normalize_grade(raw) == grade


@pytest.mark.parametrize(
    ("grade", "specialized", "band"),
    [
        ("PK", False, "prek"),
        ("K", False, "elementary"),
        ("5", False, "elementary"),
        ("6", False, "middle"),
        ("8", False, "middle"),
        ("9", False, "high"),
        ("12", False, "high"),
        (None, False, None),
        ("10", True, "specialized"),
    ],
)
def test_grade_bands(grade, specialized, band):
    assert (
        eligibility.band_for(Student(grade=grade, needs_specialized_transport=specialized)) == band
    )


# --- Eligibility -------------------------------------------------------------


def test_a_student_far_enough_from_school_is_eligible(client, admin_headers, census):
    student = _student(client, admin_headers, grade="4")
    assert _listed(client, admin_headers, student)["eligibility"] == {
        "eligible": False,
        "reason": "No home location on file",
        "miles_from_school": None,
        "band": "elementary",
    }
    assert _set_home(client, admin_headers, student).status_code == 200
    listed = _listed(client, admin_headers, student)
    assert listed["has_home"] is True
    assert listed["eligibility"]["eligible"] is True
    assert re.fullmatch(
        r"2\.(49|50) mi from school \(at least 2 mi\)", listed["eligibility"]["reason"]
    )
    assert listed["eligibility"]["miles_from_school"] == pytest.approx(2.5, abs=0.011)


def test_a_student_close_to_school_is_not_unless_an_override_applies(client, admin_headers):
    student = _student(client, admin_headers, grade="4")
    _set_home(
        client,
        admin_headers,
        student,
        location_lat=29.7 + 1.25 * MILE,
        location_lon=-95.4,
    )
    reason = _listed(client, admin_headers, student)["eligibility"]["reason"]
    assert re.fullmatch(r"1\.2[45] mi from school \(under 2 mi\)", reason)

    client.patch(
        f"/students/{student['id']}", headers=admin_headers, json={"hazardous_route": True}
    )
    assert _listed(client, admin_headers, student)["eligibility"]["reason"] == (
        "Hazardous walking route"
    )
    client.patch(
        f"/students/{student['id']}",
        headers=admin_headers,
        json={"hazardous_route": False, "needs_specialized_transport": True},
    )
    listed = _listed(client, admin_headers, student)["eligibility"]
    assert (listed["eligible"], listed["reason"], listed["band"]) == (
        True,
        "Specialized transportation",
        "specialized",
    )


def test_just_under_the_limit_never_reads_as_over_it(client, admin_headers):
    student = _student(client, admin_headers)
    _set_home(client, admin_headers, student, location_lat=29.7 + 1.999 * MILE, location_lon=-95.4)
    result = _listed(client, admin_headers, student)["eligibility"]
    assert result["eligible"] is False
    assert result["reason"].startswith("1.9")


def test_the_district_eligibility_distance_is_editable(client, admin_headers):
    student = _student(client, admin_headers)
    _set_home(client, admin_headers, student, location_lat=29.7 + 1.5 * MILE, location_lon=-95.4)
    assert _listed(client, admin_headers, student)["eligibility"]["eligible"] is False

    rules = client.get("/transportation-rules", headers=admin_headers).json()
    assert rules["is_default"] is True
    assert rules["eligibility_miles"] == 2.0
    assert rules["walk_miles"] == {
        "prek": 0.25,
        "elementary": 0.25,
        "middle": 0.5,
        "high": 0.5,
        "specialized": 0.0,
    }
    assert rules["ride_minutes"]["elementary"] == 45 and rules["ride_minutes"]["high"] == 60
    body = {k: rules[k] for k in ("walk_miles", "ride_minutes")} | {"eligibility_miles": 1.0}
    updated = client.put("/transportation-rules", headers=admin_headers, json=body)
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_default"] is False
    assert _listed(client, admin_headers, student)["eligibility"]["eligible"] is True


def test_transportation_rules_need_every_band_in_range_and_are_admin_only(
    client, admin_headers, db_session
):
    rules = client.get("/transportation-rules", headers=admin_headers).json()
    body = {k: rules[k] for k in ("eligibility_miles", "walk_miles", "ride_minutes")}
    missing = {**body, "walk_miles": {"prek": 0.25}}
    assert (
        client.put("/transportation-rules", headers=admin_headers, json=missing).status_code == 422
    )
    too_far = {**body, "walk_miles": {**body["walk_miles"], "high": 9}}
    assert (
        client.put("/transportation-rules", headers=admin_headers, json=too_far).status_code == 422
    )

    make_user(db_session, email="d@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="d@example.org"))
    assert client.get("/transportation-rules", headers=dispatcher).status_code == 200
    assert client.put("/transportation-rules", headers=dispatcher, json=body).status_code == 403
    audit = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.entity_type == "transportation_rules"
    )
    assert audit.count() == 0


# --- Home location and the Census geocoder -----------------------------------


def test_an_address_is_geocoded_with_the_census_and_only_the_address_is_sent(
    client, admin_headers, census
):
    student = _student(client, admin_headers)
    response = _set_home(client, admin_headers, student)
    assert response.status_code == 200, response.text
    home = response.json()
    assert home["source"] == "census"
    assert home["matched_address"] == "123 MAIN ST, HOUSTON, TX, 77002"
    assert home["location_lat"] == pytest.approx(29.7 + 2.5 * MILE)

    [url] = census["calls"]
    assert url.startswith("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?")
    assert "address=123+Main+St%2C+Houston%2C+TX+77002" in url
    assert "benchmark=Public_AR_Current" in url
    assert "Ana" not in url and "Lopez" not in url

    assert client.get(f"/students/{student['id']}/home", headers=admin_headers).json() == home


def test_no_census_match_or_an_outage_says_to_place_it_on_the_map(client, admin_headers, census):
    student = _student(client, admin_headers)
    census["state"]["payload"] = {"result": {"addressMatches": []}}
    no_match = _set_home(client, admin_headers, student)
    assert no_match.status_code == 422
    assert "place the home on the map" in no_match.json()["detail"]

    census["state"]["payload"] = "down"
    outage = _set_home(client, admin_headers, student)
    assert outage.status_code == 503
    assert "isn't reachable" in outage.json()["detail"]
    assert client.get(f"/students/{student['id']}/home", headers=admin_headers).status_code == 404


def test_a_hand_placed_pin_skips_the_census(client, admin_headers, census):
    student = _student(client, admin_headers)
    response = _set_home(client, admin_headers, student, location_lat=29.8, location_lon=-95.5)
    assert response.status_code == 200, response.text
    assert (response.json()["source"], response.json()["matched_address"]) == ("manual", None)
    assert census["calls"] == []
    half = _set_home(client, admin_headers, student, location_lat=29.8)
    assert half.status_code == 422


def test_homes_are_for_transportation_admins_only(client, admin_headers, db_session, census):
    student = _student(client, admin_headers)
    _set_home(client, admin_headers, student)
    make_user(db_session, email="d@example.org", role=Role.DISPATCHER)
    dispatcher = auth_headers(login(client, email="d@example.org"))
    url = f"/students/{student['id']}/home"
    assert client.get(url, headers=dispatcher).status_code == 403
    assert client.put(url, headers=dispatcher, json={"address": "x y z"}).status_code == 403
    assert client.delete(url, headers=dispatcher).status_code == 403

    # The list dispatchers read has eligibility, never the home itself.
    listed = _listed(client, dispatcher, student)
    assert listed["has_home"] is True
    flat = str(listed)
    assert "Main" not in flat and "MAIN" not in flat and "29.736" not in flat


def test_the_audit_trail_records_home_changes_without_the_address(
    client, admin_headers, db_session, census
):
    student = _student(client, admin_headers)
    _set_home(client, admin_headers, student)
    _set_home(client, admin_headers, student, location_lat=29.8, location_lon=-95.5)
    assert (
        client.delete(f"/students/{student['id']}/home", headers=admin_headers).status_code == 204
    )
    entries = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "student_home")
        .order_by(AuditLogEntry.id)
        .all()
    )
    assert [(e.action, e.after_state) for e in entries] == [
        ("home_set", {"source": "census"}),
        ("home_set", {"source": "manual"}),
        ("home_removed", None),
    ]
    assert all("Main" not in str(e.before_state) + str(e.after_state) for e in entries)
    assert _listed(client, admin_headers, student)["has_home"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"result": {}},
        {"result": {"addressMatches": [{"coordinates": {"x": "abc", "y": 1}}]}},
        {"result": {"addressMatches": [{"coordinates": {"x": -95.4, "y": 123}}]}},
    ],
)
def test_odd_census_responses_count_as_no_match(payload):
    assert census_geocoder.parse(payload) is None


# --- Editing students --------------------------------------------------------


def test_grade_accommodations_and_flags_are_editable_and_audited(client, admin_headers, db_session):
    client.post(
        "/qualifications",
        headers=admin_headers,
        json={"code": "wheelchair_lift", "kind": "vehicle_capability", "description": "Lift"},
    )
    student = _student(client, admin_headers)
    response = client.patch(
        f"/students/{student['id']}",
        headers=admin_headers,
        json={"grade": "3rd", "accommodation_codes": ["wheelchair_lift"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grade"] == "3"
    assert [q["code"] for q in body["accommodations"]] == ["wheelchair_lift"]

    [entry] = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_type == "student", AuditLogEntry.action == "updated")
        .all()
    )
    assert entry.before_state["grade"] is None and entry.after_state["grade"] == "3"
    assert entry.after_state["accommodations"] == ["wheelchair_lift"]

    bad_grade = client.patch(
        f"/students/{student['id']}", headers=admin_headers, json={"grade": "14"}
    )
    assert bad_grade.status_code == 422
    unknown = client.patch(
        f"/students/{student['id']}",
        headers=admin_headers,
        json={"accommodation_codes": ["jetpack"]},
    )
    assert unknown.status_code == 400
    cleared = client.patch(
        f"/students/{student['id']}", headers=admin_headers, json={"grade": None}
    )
    assert cleared.json()["grade"] is None


def test_the_sis_owns_grade_for_imported_students(client, admin_headers, db_session):
    _school(client, admin_headers, "Riverside", external_id="org-1")
    raw = (
        b"sourcedId,status,role,givenName,familyName,orgSourcedIds,grades\n"
        b"stu-1,active,student,Ana,Lopez,org-1,03\n"
        b'stu-2,active,student,Ben,Ng,org-1,"KG,01"\n'
    )
    assert _import(client, admin_headers, raw, dry_run=False).status_code == 200
    students = {s["full_name"]: s for s in client.get("/students", headers=admin_headers).json()}
    assert students["Ana Lopez"]["grade"] == "3"
    assert students["Ben Ng"]["grade"] == "K"

    refused = client.patch(
        f"/students/{students['Ana Lopez']['id']}", headers=admin_headers, json={"grade": "4"}
    )
    assert refused.status_code == 409
    assert "grade" in refused.json()["detail"]

    # A file without a grades column leaves grades alone.
    no_grades = (
        b"sourcedId,status,role,givenName,familyName,orgSourcedIds\n"
        b"stu-1,active,student,Ana,Lopez,org-1\n"
    )
    _import(client, admin_headers, no_grades, dry_run=False)
    assert _listed(client, admin_headers, students["Ana Lopez"])["grade"] == "3"

    # A new grade in the SIS is picked up.
    promoted = raw.replace(b",03\n", b",04\n")
    result = _import(client, admin_headers, promoted, dry_run=False).json()
    assert any("grade 3 -> 4" in (r.get("detail") or "") for r in result["rows"])
    assert _listed(client, admin_headers, students["Ana Lopez"])["grade"] == "4"
