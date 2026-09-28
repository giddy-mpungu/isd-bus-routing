"""Operational reports and CSV export (spec sections 17, 20, 21), plus GPS
position history. The district is on America/Chicago, UTC-5 in October."""

import csv
import io
from datetime import UTC, datetime, timedelta

import pytest

from isd_api import position_history, reports
from isd_api.models import AuditLogEntry, PositionSample, Role
from tests.conftest import auth_headers, login, make_user

DAY = "2026-10-05"


def _utc(hh: int, mm: int, day: int = 5) -> datetime:
    """District wall-clock HH:MM on 2026-10-DD, as UTC."""
    return datetime(2026, 10, day, hh, mm, tzinfo=UTC) + timedelta(hours=5)


def _day_with_three_runs(client, h, db_session):
    school = client.post(
        "/schools",
        headers=h,
        json={"name": "Riverside", "location_lat": 29.7, "location_lon": -95.4},
    ).json()
    driver = client.post(
        "/drivers", headers=h, json={"full_name": "Pat Driver", "license_class": "cdl_b"}
    ).json()
    vehicle = client.post("/vehicles", headers=h, json={"label": "Bus 7"}).json()
    crew = client.post(
        "/crews",
        headers=h,
        json={
            "service_date": DAY,
            "driver_id": driver["id"],
            "vehicle_id": vehicle["id"],
            "available_window_earliest": 360,
            "available_window_latest": 1000,
        },
    ).json()
    for earliest in (420, 540, 660):
        client.post(
            "/runs",
            headers=h,
            json={
                "service_date": DAY,
                "school_id": school["id"],
                "direction": "am",
                "window_earliest": earliest,
                "window_latest": earliest + 30,
                "duration_minutes": 30,
            },
        )
    assignments = client.post("/schedule", headers=h, json={"service_date": DAY}).json()[
        "assignments"
    ]
    make_user(db_session, email="pat@example.org", role=Role.DRIVER, driver_id=driver["id"])
    pat = auth_headers(login(client, email="pat@example.org"))
    return {
        "driver": driver,
        "vehicle": vehicle,
        "crew": crew,
        "assignments": sorted(assignments, key=lambda a: a["start_minute"]),
        "pat": pat,
    }


def _walk(client, pat, assignment, *statuses):
    for s in statuses:
        response = client.patch(
            f"/schedule/assignments/{assignment['id']}/status", headers=pat, json={"status": s}
        )
        assert response.status_code == 200, response.text


def _stamp(db_session, assignment, status, moment):
    """Sets when the assignment moved to `status`, as the audit trail says."""
    entry = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "assignment",
            AuditLogEntry.entity_id == assignment["id"],
            AuditLogEntry.action == "status_changed",
        )
        .all()
    )
    [match] = [e for e in entry if e.after_state["status"] == status]
    match.created_at = moment
    db_session.commit()


def _report(client, h, name, start=DAY, end=DAY):
    return client.get(f"/reports/{name}", headers=h, params={"start": start, "end": end})


def _csv(client, h, name, start=DAY, end=DAY):
    response = client.get(f"/reports/{name}/csv", headers=h, params={"start": start, "end": end})
    assert response.status_code == 200, response.text
    return response, list(csv.reader(io.StringIO(response.text.lstrip("﻿"))))


# --- Assignments and on-time performance ---------------------------------


def test_the_assignments_report_measures_on_time_from_the_audit_trail(
    client, admin_headers, db_session
):
    day = _day_with_three_runs(client, admin_headers, db_session)
    first, second, third = day["assignments"]
    # 07:00-07:30 finished at 07:33 (on time); 09:00-09:30 finished at 09:50
    # (20 late); 11:00 was a no-show.
    _walk(client, day["pat"], first, "in_progress", "completed")
    _stamp(db_session, first, "in_progress", _utc(7, 2))
    _stamp(db_session, first, "completed", _utc(7, 33))
    _walk(client, day["pat"], second, "in_progress", "completed")
    _stamp(db_session, second, "in_progress", _utc(9, 1))
    _stamp(db_session, second, "completed", _utc(9, 50))
    _walk(client, day["pat"], third, "no_show")

    response = _report(client, admin_headers, "assignments")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Assignments and on-time performance"
    assert body["total_rows"] == 3
    cols = body["columns"]
    rows = [dict(zip(cols, r, strict=True)) for r in body["rows"]]
    assert [
        (r["Planned end"], r["Started"], r["Completed"], r["Minutes late"], r["Status"])
        for r in rows
    ] == [
        ("07:30", "07:02", "07:33", 3, "Completed"),
        ("09:30", "09:01", "09:50", 20, "Completed"),
        ("11:30", None, None, None, "No-show"),
    ]
    assert rows[0]["Vehicle"] == "Bus 7" and rows[0]["Driver"] == "Pat Driver"
    assert body["summary"] == {
        "Assignments": 3,
        "Completed": 2,
        "No-show": 1,
        "On time (within 5 min)": 1,
        "Late": 1,
        "On-time %": 50.0,
        "Average minutes late (late runs)": 20.0,
    }


def test_a_dispatch_correction_counts_as_the_completion_time(client, admin_headers, db_session):
    day = _day_with_three_runs(client, admin_headers, db_session)
    first = day["assignments"][0]
    client.patch(
        f"/schedule/assignments/{first['id']}",
        headers=admin_headers,
        json={"status": "completed"},
    )
    [entry] = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.entity_id == first["id"], AuditLogEntry.action == "updated")
        .all()
    )
    entry.created_at = _utc(7, 29)
    db_session.commit()
    rows = _report(client, admin_headers, "assignments").json()["rows"]
    assert rows[0][9:12] == ["07:29", 0, "Completed"]


def test_a_time_on_another_day_shows_its_date(client, admin_headers, db_session):
    day = _day_with_three_runs(client, admin_headers, db_session)
    first = day["assignments"][0]
    _walk(client, day["pat"], first, "in_progress", "completed")
    _stamp(db_session, first, "in_progress", _utc(7, 0))
    _stamp(db_session, first, "completed", _utc(0, 10, day=6))  # after midnight
    row = _report(client, admin_headers, "assignments").json()["rows"][0]
    assert row[8:11] == ["07:00", "2026-10-06 00:10", 1000]


# --- CSV -------------------------------------------------------------------


def test_csv_download_has_every_row_a_filename_and_no_caching(client, admin_headers, db_session):
    _day_with_three_runs(client, admin_headers, db_session)
    response, table = _csv(client, admin_headers, "assignments")
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="assignments_{DAY}_{DAY}.csv"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith("﻿")
    assert table[0][:3] == ["Date", "School", "Direction"]
    assert len(table) == 4


def test_csv_neutralises_spreadsheet_formulas_but_keeps_numbers(client, admin_headers, db_session):
    day = _day_with_three_runs(client, admin_headers, db_session)
    client.post(
        f"/drivers/{day['driver']['id']}/reports",
        headers=day["pat"],
        json={
            "service_date": DAY,
            "report_type": "incident",
            "description": '=HYPERLINK("http://evil.example","click")',
        },
    )
    client.put(
        f"/drivers/{day['driver']['id']}/position",
        headers=day["pat"],
        json={
            "service_date": DAY,
            "location_lat": 29.7,
            "location_lon": -95.4,
            "recorded_at": _utc(7, 5).isoformat(),
        },
    )

    _, table = _csv(client, admin_headers, "driver-reports")
    assert table[1][-1] == '\'=HYPERLINK("http://evil.example","click")'
    _, positions = _csv(client, admin_headers, "positions")
    assert positions[1][3:] == ["2026-10-05 07:05:00", "29.7", "-95.4"]


def test_report_ranges_are_checked_and_unknown_reports_are_404(client, admin_headers):
    assert (
        _report(client, admin_headers, "assignments", "2026-10-05", "2026-10-04").status_code == 400
    )
    too_long = _report(client, admin_headers, "assignments", "2026-01-01", "2026-06-01")
    assert too_long.status_code == 400
    assert "at most 92 days" in too_long.json()["detail"]
    assert (
        _report(client, admin_headers, "positions", "2026-10-01", "2026-10-07").status_code == 200
    )
    assert (
        _report(client, admin_headers, "positions", "2026-10-01", "2026-10-08").status_code == 400
    )
    assert _report(client, admin_headers, "payroll").status_code == 404


def test_only_dispatch_and_admins_can_read_reports(client, admin_headers, db_session):
    make_user(db_session, email="d@example.org", role=Role.DISPATCHER)
    make_user(db_session, email="s@example.org", role=Role.SCHOOL_ADMIN)
    dispatcher = auth_headers(login(client, email="d@example.org"))
    school_admin = auth_headers(login(client, email="s@example.org"))
    assert _report(client, dispatcher, "assignments").status_code == 200
    assert _report(client, school_admin, "assignments").status_code == 403
    params = {"start": DAY, "end": DAY}
    assert (
        client.get("/reports/assignments/csv", headers=school_admin, params=params).status_code
        == 403
    )


def test_the_page_preview_is_capped_but_says_how_many_rows_there_are(
    client, admin_headers, db_session, monkeypatch
):
    _day_with_three_runs(client, admin_headers, db_session)
    monkeypatch.setattr(reports, "PREVIEW_ROWS", 2)
    body = _report(client, admin_headers, "assignments").json()
    assert (len(body["rows"]), body["total_rows"]) == (2, 3)
    _, table = _csv(client, admin_headers, "assignments")
    assert len(table) == 4


# --- The other reports -----------------------------------------------------


def test_the_field_trips_report_shows_how_late_trips_came_back(client, admin_headers):
    trip = client.post(
        "/field-trips",
        headers=admin_headers,
        json={
            "requesting_party": "Grade 5",
            "origin": "Riverside",
            "destination": "Science Museum",
            "departure_at": f"{DAY}T09:00:00",
            "expected_return_at": f"{DAY}T13:30:00",
            "passenger_count": 24,
            "trip_contact": "Ms. Patel",
        },
    ).json()
    client.patch(
        f"/field-trips/{trip['id']}",
        headers=admin_headers,
        json={"actual_return_at": f"{DAY}T14:10:00", "status": "completed"},
    )
    body = _report(client, admin_headers, "field-trips").json()
    [row] = body["rows"]
    assert row[:7] == [
        trip["id"],
        "Grade 5",
        "Science Museum",
        "2026-10-05 09:00",
        "2026-10-05 13:30",
        "2026-10-05 14:10",
        40,
    ]
    assert body["summary"] == {
        "Trips": 1,
        "Completed": 1,
        "Returned later than expected": 1,
        "Passengers carried": 24,
    }


def test_the_absences_report_counts_runs_nobody_has_covered(client, admin_headers, db_session):
    day = _day_with_three_runs(client, admin_headers, db_session)
    client.post(
        f"/drivers/{day['driver']['id']}/absences",
        headers=admin_headers,
        json={"service_date": DAY, "start_minute": 400, "end_minute": 600, "reason": "sick_leave"},
    )
    body = _report(client, admin_headers, "absences").json()
    assert body["rows"] == [[DAY, "Pat Driver", "sick leave", "06:40", "10:00", 2]]
    assert body["summary"]["Runs still on an absent driver"] == 2

    # A substitute takes over the crew: nothing is left uncovered.
    sub = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Sam Sub", "license_class": "cdl_b"}
    ).json()
    client.patch(
        f"/crews/{day['crew']['id']}", headers=admin_headers, json={"driver_id": sub["id"]}
    )
    assert _report(client, admin_headers, "absences").json()["rows"][0][-1] == 0


def test_the_dispatch_tasks_report_marks_cancelled_tasks(client, admin_headers):
    driver = client.post(
        "/drivers", headers=admin_headers, json={"full_name": "Sam", "license_class": "cdl_b"}
    ).json()
    ids = []
    for start in (600, 700):
        ids.append(
            client.post(
                "/dispatch-tasks",
                headers=admin_headers,
                json={
                    "kind": "move_vehicle",
                    "service_date": DAY,
                    "start_minute": start,
                    "end_minute": start + 30,
                    "driver_id": driver["id"],
                    "instructions": "Take Bus 9 to the shop.",
                },
            ).json()["id"]
        )
    client.post(f"/dispatch-tasks/{ids[1]}/cancel", headers=admin_headers)
    body = _report(client, admin_headers, "dispatch-tasks").json()
    assert [r[8] for r in body["rows"]] == ["Sent", "Cancelled"]
    assert body["summary"] == {"Tasks": 2, "Completed": 0, "Cancelled": 1}


# --- Position history ------------------------------------------------------


def _report_position(client, day, moment, lat=29.7, lon=-95.4):
    response = client.put(
        f"/drivers/{day['driver']['id']}/position",
        headers=day["pat"],
        json={
            "service_date": DAY,
            "location_lat": lat,
            "location_lon": lon,
            "recorded_at": moment.isoformat(),
        },
    )
    assert response.status_code == 204, response.text


def test_every_position_report_is_kept_as_a_track(client, admin_headers, db_session):
    day = _day_with_three_runs(client, admin_headers, db_session)
    _report_position(client, day, _utc(7, 0), 29.70, -95.40)
    _report_position(client, day, _utc(7, 1), 29.71, -95.41)
    _report_position(client, day, _utc(7, 1), 29.71, -95.41)  # a retried request
    _report_position(client, day, _utc(7, 2), 29.72, -95.42)

    track = client.get(
        f"/schedule/{DAY}/fleet-positions/{day['crew']['id']}/track", headers=admin_headers
    )
    assert track.status_code == 200, track.text
    assert [(p["location_lat"], p["location_lon"]) for p in track.json()] == [
        (29.70, -95.40),
        (29.71, -95.41),
        (29.72, -95.42),
    ]
    # The live view still holds just the latest.
    [latest] = client.get(f"/schedule/{DAY}/fleet-positions", headers=admin_headers).json()
    assert latest["location_lat"] == 29.72


def test_tracks_are_for_dispatch_only_and_per_date(client, admin_headers, db_session):
    day = _day_with_three_runs(client, admin_headers, db_session)
    url = f"/schedule/{DAY}/fleet-positions/{day['crew']['id']}/track"
    assert client.get(url, headers=day["pat"]).status_code == 403
    wrong_day = f"/schedule/2026-10-06/fleet-positions/{day['crew']['id']}/track"
    assert client.get(wrong_day, headers=admin_headers).status_code == 404


def test_history_older_than_the_retention_period_is_deleted(
    client, admin_headers, db_session, monkeypatch
):
    day = _day_with_three_runs(client, admin_headers, db_session)
    _report_position(client, day, _utc(7, 0))
    _report_position(client, day, _utc(8, 0))
    monkeypatch.setattr(position_history.settings, "position_history_days", 30)

    deleted = position_history.prune(db_session, now=_utc(7, 30) + timedelta(days=30))
    db_session.commit()

    assert deleted == 1
    assert [s.recorded_at.hour for s in db_session.query(PositionSample)] == [13]  # 08:00 CDT


def test_pruning_runs_at_most_hourly_on_the_write_path(
    client, admin_headers, db_session, monkeypatch
):
    calls = []
    monkeypatch.setattr(position_history, "_last_prune", None)
    monkeypatch.setattr(position_history, "prune", lambda db: calls.append(1) or 0)
    clock = iter([1000.0, 1500.0, 1000.0 + position_history.PRUNE_INTERVAL_SECONDS])
    monkeypatch.setattr(position_history, "_monotonic", lambda: next(clock))

    day = _day_with_three_runs(client, admin_headers, db_session)
    for minute in (0, 1, 2):
        _report_position(client, day, _utc(7, minute))

    assert calls == [1, 1]


@pytest.mark.parametrize("value", ["-1", "+1", "@SUM(A1)", "\tx", "plain"])
def test_csv_cell_prefixing(value):
    report = reports.Report("x", "X", ["A"], rows=[[value], [-95.4]])
    table = list(csv.reader(io.StringIO(reports.to_csv(report))))
    expected = value if value == "plain" else "'" + value
    assert table[1] == [expected]
    assert table[2] == ["-95.4"]
