"""Operational reports over a date range (spec sections 17 "Reports", 20
historical data, 21 historical records), shown on the Reports page and
exported as CSV.

Each report is columns + rows + a small summary. Cells keep their type
(numbers stay numbers) until `to_csv`, which also neutralises text that a
spreadsheet would run as a formula (CSV injection: descriptions and names
are user-entered).

Times are district wall-clock (the ridership rules' time zone), the same
clock the schedule's minute-of-day windows use.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from isd_api import ridership_rules, tracking
from isd_api.assignment_states import LABELS
from isd_api.availability import trip_return
from isd_api.models import (
    Assignment,
    AssignmentStatus,
    AuditLogEntry,
    Crew,
    DispatchTask,
    DriverAbsence,
    DriverReport,
    FieldTrip,
    PositionSample,
    Run,
)

Cell = str | int | float | None

# A completed run counts as on time if it finished within this many minutes
# of its planned end.
ON_TIME_GRACE_MINUTES = 5
MAX_RANGE_DAYS = 92
# GPS history is dense (a report every ~20 s per bus), so a shorter range.
MAX_POSITION_RANGE_DAYS = 7
# The page previews this many rows; the CSV has them all.
PREVIEW_ROWS = 500


@dataclass
class Report:
    name: str
    title: str
    columns: list[str]
    rows: list[list[Cell]] = field(default_factory=list)
    summary: dict[str, Cell] = field(default_factory=dict)


def hhmm(minute: int) -> str:
    return ridership_rules.hhmm(minute)


def _local(moment: datetime, tz: ZoneInfo) -> datetime:
    return (moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)).astimezone(tz)


def _local_minute(moment: datetime, tz: ZoneInfo, service_date: date) -> int:
    """Minute of `service_date` in district time (can pass 1439 or go
    negative when the moment falls on another day)."""
    local = _local(moment, tz)
    return (local.date() - service_date).days * 1440 + local.hour * 60 + local.minute


def _clock(moment: datetime | None, tz: ZoneInfo, service_date: date) -> str | None:
    """HH:MM in district time, with the date when it's not the service date."""
    if moment is None:
        return None
    local = _local(moment, tz)
    return local.strftime("%H:%M" if local.date() == service_date else "%Y-%m-%d %H:%M")


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


# --- Assignments and on-time performance ---------------------------------


def _status_times(
    db: Session, assignment_ids: list[int]
) -> dict[int, tuple[datetime | None, datetime | None]]:
    """(first time In progress, last time Completed) per assignment, from
    the audit trail (drivers' taps and dispatch corrections alike)."""
    times: dict[int, tuple[datetime | None, datetime | None]] = {}
    if not assignment_ids:
        return times
    entries = (
        db.query(AuditLogEntry)
        .filter(
            AuditLogEntry.entity_type == "assignment",
            AuditLogEntry.entity_id.in_(assignment_ids),
            AuditLogEntry.action.in_(("status_changed", "updated")),
        )
        .order_by(AuditLogEntry.created_at, AuditLogEntry.id)
    )
    for entry in entries:
        before = (entry.before_state or {}).get("status")
        after = (entry.after_state or {}).get("status")
        if after is None or after == before:
            continue
        started, completed = times.get(entry.entity_id, (None, None))
        if after == AssignmentStatus.IN_PROGRESS.value and started is None:
            started = entry.created_at
        if after == AssignmentStatus.COMPLETED.value:
            completed = entry.created_at
        times[entry.entity_id] = (started, completed)
    return times


def assignments_report(db: Session, start: date, end: date, tz: ZoneInfo) -> Report:
    report = Report(
        "assignments",
        "Assignments and on-time performance",
        [
            "Date",
            "School",
            "Direction",
            "Window",
            "Vehicle",
            "Driver",
            "Planned start",
            "Planned end",
            "Started",
            "Completed",
            "Minutes late",
            "Status",
        ],
    )
    assignments = (
        db.query(Assignment)
        .join(Run, Assignment.run_id == Run.id)
        .filter(Run.service_date >= start, Run.service_date <= end)
        .order_by(Run.service_date, Assignment.start_minute, Assignment.id)
        .all()
    )
    times = _status_times(db, [a.id for a in assignments])
    completed = on_time = no_show = 0
    late_minutes: list[int] = []
    for a in assignments:
        day = a.run.service_date
        started_at, completed_at = times.get(a.id, (None, None))
        late: int | None = None
        if a.status == AssignmentStatus.COMPLETED:
            completed += 1
            if completed_at is not None:
                late = max(0, _local_minute(completed_at, tz, day) - a.end_minute)
                if late <= ON_TIME_GRACE_MINUTES:
                    on_time += 1
                else:
                    late_minutes.append(late)
        elif a.status == AssignmentStatus.NO_SHOW:
            no_show += 1
        report.rows.append(
            [
                day.isoformat(),
                a.run.school.name,
                a.run.direction.value.upper(),
                f"{hhmm(a.run.window_earliest)}-{hhmm(a.run.window_latest)}",
                a.crew.vehicle.label,
                a.crew.driver.full_name,
                hhmm(a.start_minute),
                hhmm(a.end_minute),
                _clock(started_at, tz, day),
                _clock(completed_at, tz, day),
                late,
                LABELS[a.status],
            ]
        )
    timed = on_time + len(late_minutes)
    report.summary = {
        "Assignments": len(assignments),
        "Completed": completed,
        "No-show": no_show,
        f"On time (within {ON_TIME_GRACE_MINUTES} min)": on_time,
        "Late": len(late_minutes),
        "On-time %": _pct(on_time, timed),
        "Average minutes late (late runs)": round(sum(late_minutes) / len(late_minutes), 1)
        if late_minutes
        else None,
    }
    return report


# --- Field trips -----------------------------------------------------------


def field_trips_report(db: Session, start: date, end: date, tz: ZoneInfo) -> Report:
    report = Report(
        "field-trips",
        "Field trips",
        [
            "Trip",
            "Requesting party",
            "Destination",
            "Departure",
            "Expected return",
            "Actual return",
            "Minutes over",
            "Driver",
            "Vehicle",
            "Passengers",
            "Status",
        ],
    )
    trips = [
        t
        for t in db.query(FieldTrip).order_by(FieldTrip.departure_at)
        if start <= t.departure_at.date() <= end
    ]
    returned_late = 0
    for t in trips:
        over: int | None = None
        if t.actual_return_at is not None:
            over = int((trip_return(t) - t.expected_return_at).total_seconds() // 60)
            if over > 0:
                returned_late += 1
        report.rows.append(
            [
                t.id,
                t.requesting_party,
                t.destination,
                t.departure_at.strftime("%Y-%m-%d %H:%M"),
                t.expected_return_at.strftime("%Y-%m-%d %H:%M"),
                t.actual_return_at.strftime("%Y-%m-%d %H:%M") if t.actual_return_at else None,
                over,
                t.assigned_driver.full_name if t.assigned_driver else None,
                t.assigned_vehicle.label if t.assigned_vehicle else None,
                t.passenger_count,
                t.status.value.replace("_", " "),
            ]
        )
    report.summary = {
        "Trips": len(trips),
        "Completed": sum(1 for t in trips if t.status.value == "completed"),
        "Returned later than expected": returned_late,
        "Passengers carried": sum(t.passenger_count for t in trips),
    }
    return report


# --- Absences and cover ----------------------------------------------------


def absences_report(db: Session, start: date, end: date, tz: ZoneInfo) -> Report:
    report = Report(
        "absences",
        "Driver absences and cover",
        ["Date", "Driver", "Reason", "From", "To", "Runs still on this driver"],
    )
    absences = (
        db.query(DriverAbsence)
        .filter(DriverAbsence.service_date >= start, DriverAbsence.service_date <= end)
        .order_by(DriverAbsence.service_date, DriverAbsence.start_minute)
        .all()
    )
    uncovered_total = 0
    for absence in absences:
        # Runs inside the absence that are still on this driver: nobody has
        # covered them. (Covered runs have moved to another crew, or the
        # crew has a substitute driver, so they no longer show here.)
        on_this_driver = [
            a
            for a in db.query(Assignment)
            .join(Crew, Assignment.crew_id == Crew.id)
            .filter(Crew.service_date == absence.service_date, Crew.driver_id == absence.driver_id)
            if a.start_minute < absence.end_minute and absence.start_minute < a.end_minute
        ]
        uncovered_total += len(on_this_driver)
        report.rows.append(
            [
                absence.service_date.isoformat(),
                absence.driver.full_name,
                absence.reason.value.replace("_", " "),
                hhmm(absence.start_minute),
                hhmm(absence.end_minute),
                len(on_this_driver),
            ]
        )
    report.summary = {
        "Absences": len(absences),
        "Drivers": len({a.driver_id for a in absences}),
        "Runs still on an absent driver": uncovered_total,
    }
    return report


# --- Driver reports --------------------------------------------------------


def driver_reports_report(db: Session, start: date, end: date, tz: ZoneInfo) -> Report:
    report = Report(
        "driver-reports",
        "Incident and vehicle defect reports",
        ["Date", "Filed at", "Driver", "Vehicle", "Type", "Description"],
    )
    reports = (
        db.query(DriverReport)
        .filter(DriverReport.service_date >= start, DriverReport.service_date <= end)
        .order_by(DriverReport.service_date, DriverReport.created_at)
        .all()
    )
    for r in reports:
        report.rows.append(
            [
                r.service_date.isoformat(),
                _local(r.created_at, tz).strftime("%Y-%m-%d %H:%M"),
                r.driver.full_name,
                r.vehicle.label if r.vehicle else None,
                r.report_type.value.replace("_", " "),
                r.description,
            ]
        )
    counts = Counter(r.report_type.value for r in reports)
    report.summary = {
        "Reports": len(reports),
        "Incidents": counts.get("incident", 0),
        "Vehicle defects": counts.get("vehicle_defect", 0),
    }
    return report


# --- Dispatch tasks --------------------------------------------------------


def dispatch_tasks_report(db: Session, start: date, end: date, tz: ZoneInfo) -> Report:
    report = Report(
        "dispatch-tasks",
        "Dispatch tasks",
        [
            "Date",
            "Task",
            "Kind",
            "Driver",
            "Vehicle",
            "From",
            "To",
            "Location",
            "Status",
            "Instructions",
        ],
    )
    tasks = (
        db.query(DispatchTask)
        .filter(DispatchTask.service_date >= start, DispatchTask.service_date <= end)
        .order_by(DispatchTask.service_date, DispatchTask.start_minute, DispatchTask.id)
        .all()
    )
    for t in tasks:
        report.rows.append(
            [
                t.service_date.isoformat(),
                t.id,
                t.kind.value.replace("_", " "),
                t.driver.full_name,
                t.vehicle.label if t.vehicle else None,
                hhmm(t.start_minute),
                hhmm(t.end_minute),
                t.location,
                "Cancelled" if t.cancelled_at else LABELS[t.status],
                t.instructions,
            ]
        )
    report.summary = {
        "Tasks": len(tasks),
        "Completed": sum(1 for t in tasks if t.status == AssignmentStatus.COMPLETED),
        "Cancelled": sum(1 for t in tasks if t.cancelled_at is not None),
    }
    return report


# --- GPS positions ---------------------------------------------------------


def positions_report(db: Session, start: date, end: date, tz: ZoneInfo) -> Report:
    report = Report(
        "positions",
        "GPS position history",
        [
            "Date",
            "Vehicle",
            "Driver",
            "Recorded at",
            "Latitude",
            "Longitude",
            "Run",
            "Metres from route",
        ],
    )
    samples = (
        db.query(PositionSample)
        .join(Crew, PositionSample.crew_id == Crew.id)
        .filter(Crew.service_date >= start, Crew.service_date <= end)
        .order_by(Crew.service_date, PositionSample.crew_id, PositionSample.recorded_at)
        .all()
    )
    # Spec section 20 "route deviations": each sample against the route of
    # the run its crew was on at that minute (tracking.py's straight-line
    # route through the day's stops), when there was one.
    lines: dict[int, list[tuple[float, float]]] = {}
    off_route = 0
    for s in samples:
        minute = _local_minute(s.recorded_at, tz, s.crew.service_date)
        running = next(
            (a for a in s.crew.assignments if a.start_minute <= minute <= a.end_minute), None
        )
        away: Cell = None
        label: Cell = None
        if running is not None:
            label = f"{running.run.school.name} {running.run.direction.value.upper()}"
            if running.id not in lines:
                lines[running.id] = tracking.route_line(db, running)
            line = lines[running.id]
            if len(line) >= 2:
                metres = round(tracking.distance_from_line((s.location_lat, s.location_lon), line))
                away = metres
                if metres > tracking.OFF_ROUTE_METERS:
                    off_route += 1
        report.rows.append(
            [
                s.crew.service_date.isoformat(),
                s.crew.vehicle.label,
                s.crew.driver.full_name,
                _local(s.recorded_at, tz).strftime("%Y-%m-%d %H:%M:%S"),
                s.location_lat,
                s.location_lon,
                label,
                away,
            ]
        )
    report.summary = {
        "Positions": len(samples),
        "Buses": len({s.crew.vehicle_id for s in samples}),
        f"Over {tracking.OFF_ROUTE_METERS} m from the route": off_route,
    }
    return report


BUILDERS: dict[str, tuple[Callable[[Session, date, date, ZoneInfo], Report], int]] = {
    "assignments": (assignments_report, MAX_RANGE_DAYS),
    "field-trips": (field_trips_report, MAX_RANGE_DAYS),
    "absences": (absences_report, MAX_RANGE_DAYS),
    "driver-reports": (driver_reports_report, MAX_RANGE_DAYS),
    "dispatch-tasks": (dispatch_tasks_report, MAX_RANGE_DAYS),
    "positions": (positions_report, MAX_POSITION_RANGE_DAYS),
}


class RangeError(ValueError):
    pass


def build(db: Session, name: str, start: date, end: date) -> Report:
    """Raises KeyError for an unknown report, RangeError for a bad range."""
    builder, max_days = BUILDERS[name]
    if end < start:
        raise RangeError("end must be on or after start")
    if (end - start).days + 1 > max_days:
        raise RangeError(f"This report covers at most {max_days} days at a time")
    tz = ZoneInfo(ridership_rules.load_rules(db).timezone)
    return builder(db, start, end, tz)


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value: Cell) -> Cell:
    # Text a spreadsheet would treat as a formula is prefixed with a quote
    # (OWASP's CSV-injection advice). Real numbers are left alone, so a
    # negative longitude stays a number.
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def to_csv(report: Report) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(report.columns)
    for row in report.rows:
        writer.writerow(["" if v is None else _csv_cell(v) for v in row])
    return buffer.getvalue()
