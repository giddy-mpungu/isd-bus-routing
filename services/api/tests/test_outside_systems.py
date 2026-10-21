"""Phase D of the October review: absences from HR as CSV (spec sections 13,
19) and school attendance zones from the district's GIS (section 3)."""

from isd_api import zones
from isd_api.models import DriverAbsence

DAY = "2026-10-21"


def _driver(client, h, name, employee_id=None):
    body = {"full_name": name, "license_class": "cdl_b"}
    if employee_id:
        body["employee_id"] = employee_id
    response = client.post("/drivers", headers=h, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _import(client, h, text, dry_run=True):
    return client.post(
        "/absences/import",
        headers=h,
        params={"dry_run": str(dry_run).lower()},
        json={"csv": text},
    )


CSV = (
    "employee_id,driver,date,start,end,reason\n"
    f"E100,,{DAY},,,sick leave\n"
    f",Sam Okafor,{DAY},13:00,15:30,training\n"
    f",Nobody Here,{DAY},,,\n"
    f"E999,,{DAY},,,\n"
    f",Sam Okafor,2026-13-01,,,\n"
    f",Sam Okafor,{DAY},15:00,14:00,\n"
    f",Sam Okafor,{DAY},,,napping\n"
)


def test_an_hr_export_is_previewed_then_imported(client, admin_headers, db_session):
    h = admin_headers
    jordan = _driver(client, h, "Jordan Rivera", "E100")
    sam = _driver(client, h, "Sam Okafor")

    preview = _import(client, h, CSV)
    assert preview.status_code == 200, preview.text
    rows = preview.json()["rows"]
    assert preview.json()["applied"] is False
    assert [(r["line"], r["outcome"]) for r in rows] == [
        (2, "created"),
        (3, "created"),
        (4, "error"),
        (5, "error"),
        (6, "error"),
        (7, "error"),
        (8, "error"),
    ]
    assert rows[0]["driver"] == "Jordan Rivera"
    assert [r["message"] for r in rows[2:]] == [
        "No driver by that name",
        "No driver has that employee ID",
        "The date must be YYYY-MM-DD",
        "The start must come before the end",
        rows[6]["message"],
    ]
    assert rows[6]["message"].startswith("Unknown reason")
    assert db_session.query(DriverAbsence).count() == 0

    applied = _import(client, h, CSV, dry_run=False).json()
    assert applied["applied"] is True
    absences = {
        (a.driver_id, a.start_minute, a.end_minute, a.reason.value)
        for a in db_session.query(DriverAbsence)
    }
    assert absences == {
        (jordan["id"], 0, 1439, "sick_leave"),
        (sam["id"], 780, 930, "training"),
    }

    # The same export again changes nothing.
    again = _import(client, h, CSV, dry_run=False).json()
    assert [r["outcome"] for r in again["rows"][:2]] == ["unchanged", "unchanged"]
    assert db_session.query(DriverAbsence).count() == 2


def test_two_drivers_with_one_name_need_an_employee_id(client, admin_headers):
    h = admin_headers
    _driver(client, h, "Alex Kim")
    _driver(client, h, "Alex Kim")
    [row] = _import(client, h, f"driver,date\nAlex Kim,{DAY}\n").json()["rows"]
    assert row["message"] == "More than one driver has that name; give an employee ID"


def test_a_csv_without_the_columns_is_refused(client, admin_headers):
    response = _import(client, admin_headers, "name,when\nx,y\n")
    assert response.status_code == 400


def test_employee_ids_are_unique(client, admin_headers):
    _driver(client, admin_headers, "Jordan Rivera", "E100")
    response = client.post(
        "/drivers",
        headers=admin_headers,
        json={"full_name": "Sam", "license_class": "cdl_b", "employee_id": "E100"},
    )
    assert response.status_code == 409
    assert "already Jordan Rivera's" in response.json()["detail"]


# --- attendance zones ---------------------------------------------------

# A square around the school, about 2.2 km on a side, with a hole in it.
SQUARE = {
    "type": "Feature",
    "properties": {"name": "Riverside zone"},
    "geometry": {
        "type": "Polygon",
        "coordinates": [
            [[-95.42, 29.68], [-95.38, 29.68], [-95.38, 29.72], [-95.42, 29.72], [-95.42, 29.68]],
            [[-95.41, 29.69], [-95.40, 29.69], [-95.40, 29.70], [-95.41, 29.70], [-95.41, 29.69]],
        ],
    },
}


def test_point_in_zone_respects_holes():
    geometry = zones.geometry_from_upload(SQUARE)
    assert zones.contains(geometry, 29.715, -95.39)
    assert not zones.contains(geometry, 29.695, -95.405)  # in the hole
    assert not zones.contains(geometry, 29.75, -95.39)


def test_bad_boundaries_are_refused_with_a_reason(client, admin_headers):
    school = client.post(
        "/schools",
        headers=admin_headers,
        json={"name": "R", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    for bad, why in (
        ({"type": "Point", "coordinates": [-95.4, 29.7]}, "Polygon or MultiPolygon"),
        ({"type": "Polygon", "coordinates": [[[-95.4, 29.7], [-95.3, 29.7]]]}, "four points"),
        ({"type": "FeatureCollection", "features": []}, "a single feature"),
    ):
        response = client.put(
            f"/schools/{school['id']}/zone", headers=admin_headers, json={"geojson": bad}
        )
        assert response.status_code == 400
        assert why in response.json()["detail"]


def test_a_home_outside_the_zone_isnt_eligible(client, admin_headers):
    h = admin_headers
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.70, "location_lon": -95.40},
    ).json()
    inside, outside, specialized = (
        client.post(
            "/students",
            headers=h,
            json={"full_name": name, "school_id": school["id"], "grade": "3", **extra},
        ).json()
        for name, extra in (
            ("In Zone", {}),
            ("Out Of Zone", {}),
            ("Special Program", {"needs_specialized_transport": True}),
        )
    )
    # Inside the square, far enough to ride; and well outside it.
    for student, lat, lon in (
        (inside, 29.718, -95.381),
        (outside, 29.75, -95.40),
        (specialized, 29.75, -95.40),
    ):
        client.put(
            f"/students/{student['id']}/home",
            headers=h,
            json={"address": "1 Main St", "location_lat": lat, "location_lon": lon},
        )

    def eligibility():
        return {
            s["full_name"]: (s["eligibility"]["eligible"], s["eligibility"]["reason"])
            for s in client.get("/students", headers=h).json()
        }

    before = eligibility()
    assert before["Out Of Zone"][0] is True  # 3.3 mi away, no zone yet

    saved = client.put(f"/schools/{school['id']}/zone", headers=h, json={"geojson": SQUARE})
    assert saved.status_code == 200, saved.text
    assert saved.json()["has_zone"] is True
    after = eligibility()
    assert after["Out Of Zone"] == (False, "Lives outside the school's attendance zone")
    assert after["Special Program"][0] is True
    assert after["In Zone"][1] != "Lives outside the school's attendance zone"
    assert client.get(f"/schools/{school['id']}/zone", headers=h).json()["type"] == "Polygon"

    removed = client.delete(f"/schools/{school['id']}/zone", headers=h).json()
    assert removed["has_zone"] is False
    assert eligibility()["Out Of Zone"][0] is True
