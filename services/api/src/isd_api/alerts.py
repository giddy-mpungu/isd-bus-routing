"""Operational alerts for dispatch (spec sections 9, 13.1, 14, 16, 18): what
needs someone's attention on a service date, worked out from live data
each time it's asked for. Nothing is stored, so an alert disappears as
soon as its cause is fixed.

Critical:
  - a run with no bus assigned,
  - a run whose crew can no longer do it (absence, field trip or dispatch
    task over it): "needs cover"; or whose bus can't (out of service, in
    maintenance, inspection expired): "needs a bus", with spare buses
    offered (isd_api/maintenance.py),
  - a bus in service whose inspection has expired by that day,
  - a run or dispatch task not started `START_GRACE_MINUTES` after its
    start time, or marked no-show,
  - a field trip departing that day with no driver or no bus,
  - an incident report,
  - a stop of a run's trip inside a road closure in force (spec section 10),
  - a run whose assigned times fall outside its window, not yet started
    (its school's bells changed after it was scheduled, isd_api/bells.py).
Warning:
  - work not yet acknowledged within `ACK_WARNING_MINUTES` of its start,
  - work still under way `FINISH_GRACE_MINUTES` after its planned end,
  - no GPS for `GPS_STALE_MINUTES` from a bus whose run is under way,
  - a field trip past its expected return with no return recorded,
  - a vehicle defect report not yet dealt with (still open),
  - a bus in service whose service or inspection falls due within
    `maintenance.DUE_WARNING_DAYS` of that day, or whose service is overdue,
  - a run's trip passing near a road closure in force (its directions avoid it).

Time-based checks use the district's clock (`ridership_rules`). For
today they compare with the current time. A past day is treated as over,
so what never started or finished still shows; a future day has no
time-based alerts yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from isd_api import closures, maintenance, ridership_rules
from isd_api.assignment_states import LABELS, TERMINAL, UNDERWAY
from isd_api.availability import (
    assignment_availability_issue,
    trip_return,
    trip_windows,
    vehicle_conflict_for_window,
)
from isd_api.models import (
    Assignment,
    AssignmentStatus,
    Crew,
    DefectStatus,
    DispatchTask,
    DriverReport,
    DriverReportType,
    FieldTrip,
    Run,
    TripStatus,
    Vehicle,
    VehiclePosition,
)

# Unacknowledged work this close to its start is flagged.
ACK_WARNING_MINUTES = 30
# Work not under way this long after its start is late.
START_GRACE_MINUTES = 10
# Work still under way this long after its planned end is overrunning.
FINISH_GRACE_MINUTES = 15
# A bus under way that hasn't reported for this long has gone quiet.
GPS_STALE_MINUTES = 5

CRITICAL = "critical"
WARNING = "warning"
_SEVERITY_ORDER = {CRITICAL: 0, WARNING: 1}

_NOT_STARTED = {AssignmentStatus.SENT, AssignmentStatus.RECEIVED, AssignmentStatus.ACKNOWLEDGED}
_NOT_ACKNOWLEDGED = {AssignmentStatus.SENT, AssignmentStatus.RECEIVED}


@dataclass(frozen=True)
class Alert:
    kind: str
    severity: str
    message: str
    entity_type: str
    entity_id: int
    minute: int | None = None


@dataclass(frozen=True)
class DayAlerts:
    # HH:MM in the district when the date is today, else None.
    district_time: str | None
    alerts: list[Alert]


hhmm = ridership_rules.hhmm


def _run_label(run: Run) -> str:
    return f"{run.school.name} {run.direction.value.upper()} run"


def _as_utc(moment: datetime) -> datetime:
    # SQLite hands back naive datetimes; everything is stored in UTC.
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _timing_alerts(
    *,
    status: AssignmentStatus,
    start: int,
    end: int,
    now_minute: int | None,
    label: str,
    who: str,
    entity_type: str,
    entity_id: int,
) -> list[Alert]:
    """Late start, not acknowledged, overrunning, and no-show, shared by
    runs and dispatch tasks."""
    if status == AssignmentStatus.NO_SHOW:
        return [
            Alert(
                "no_show",
                CRITICAL,
                f"{label} was marked no-show ({who})",
                entity_type,
                entity_id,
                start,
            )
        ]
    if now_minute is None or status in TERMINAL:
        return []
    state = LABELS[status].lower()
    if status in _NOT_STARTED and now_minute >= start + START_GRACE_MINUTES:
        return [
            Alert(
                "late_start",
                CRITICAL,
                f"{label} hasn't started: due at {hhmm(start)}, still {state} ({who})",
                entity_type,
                entity_id,
                start,
            )
        ]
    if status in _NOT_ACKNOWLEDGED and now_minute >= start - ACK_WARNING_MINUTES:
        return [
            Alert(
                "not_acknowledged",
                WARNING,
                f"{who} hasn't acknowledged {label}, starting at {hhmm(start)}",
                entity_type,
                entity_id,
                start,
            )
        ]
    if status in UNDERWAY and now_minute >= end + FINISH_GRACE_MINUTES:
        return [
            Alert(
                "overrunning",
                WARNING,
                f"{label} was due to finish at {hhmm(end)} and is still {state} ({who})",
                entity_type,
                entity_id,
                end,
            )
        ]
    return []


def day_alerts(db: Session, service_date: date, now: datetime | None = None) -> DayAlerts:
    rules = ridership_rules.load_rules(db)
    now = now or ridership_rules.utc_now()
    local = ridership_rules.district_now(rules, now)
    now_minute: int | None
    district_time: str | None
    if service_date == local.date():
        now_minute = local.hour * 60 + local.minute
        district_time = hhmm(now_minute)
    elif service_date < local.date():
        now_minute, district_time = 24 * 60, None
    else:
        now_minute, district_time = None, None
    is_today = district_time is not None

    alerts: list[Alert] = []

    runs = db.query(Run).filter(Run.service_date == service_date).order_by(Run.window_earliest)
    assignments = (
        db.query(Assignment)
        .join(Run, Assignment.run_id == Run.id)
        .filter(Run.service_date == service_date)
        .order_by(Assignment.start_minute)
        .all()
    )
    assigned_run_ids = {a.run_id for a in assignments}
    for run in runs:
        if run.id not in assigned_run_ids:
            alerts.append(
                Alert(
                    "unassigned_run",
                    CRITICAL,
                    f"No bus assigned to {_run_label(run)} "
                    f"({hhmm(run.window_earliest)}-{hhmm(run.window_latest)})",
                    "run",
                    run.id,
                    run.window_earliest,
                )
            )

    positions = {
        p.crew_id: p
        for p in db.query(VehiclePosition)
        .join(Crew, VehiclePosition.crew_id == Crew.id)
        .filter(Crew.service_date == service_date)
    }
    for a in assignments:
        label = (
            f"{_run_label(a.run)} on {a.crew.vehicle.label} "
            f"({hhmm(a.start_minute)}-{hhmm(a.end_minute)})"
        )
        who = a.crew.driver.full_name
        if a.status in _NOT_STARTED and (
            a.start_minute < a.run.window_earliest or a.end_minute > a.run.window_latest
        ):
            alerts.append(
                Alert(
                    "outside_window",
                    CRITICAL,
                    f"{label} no longer fits its window "
                    f"({hhmm(a.run.window_earliest)}-{hhmm(a.run.window_latest)}), "
                    "probably after a bell change. Run the schedule again for this day.",
                    "assignment",
                    a.id,
                    a.start_minute,
                )
            )
        if a.status not in TERMINAL:
            issue = assignment_availability_issue(db, a)
            bus_issue = vehicle_conflict_for_window(
                db, a.crew.vehicle, service_date, a.start_minute, a.end_minute
            )
            if bus_issue is not None:
                alerts.append(
                    Alert(
                        "needs_bus",
                        CRITICAL,
                        f"Needs a bus: {label}: {bus_issue}",
                        "assignment",
                        a.id,
                        a.start_minute,
                    )
                )
            elif issue is not None:
                alerts.append(
                    Alert(
                        "needs_cover",
                        CRITICAL,
                        f"Needs cover: {label}: {issue}",
                        "assignment",
                        a.id,
                        a.start_minute,
                    )
                )
        alerts += _timing_alerts(
            status=a.status,
            start=a.start_minute,
            end=a.end_minute,
            now_minute=now_minute,
            label=label,
            who=who,
            entity_type="assignment",
            entity_id=a.id,
        )
        if is_today and a.status in UNDERWAY:
            position = positions.get(a.crew_id)
            silent_for = (
                None
                if position is None
                else int((now - _as_utc(position.recorded_at)).total_seconds() // 60)
            )
            if silent_for is None or silent_for >= GPS_STALE_MINUTES:
                how_long = "yet" if silent_for is None else f"for {silent_for} min"
                alerts.append(
                    Alert(
                        "no_gps",
                        WARNING,
                        f"No GPS from {a.crew.vehicle.label} {how_long} while {label} is under way",
                        "assignment",
                        a.id,
                        a.start_minute,
                    )
                )

    tasks = (
        db.query(DispatchTask)
        .filter(DispatchTask.service_date == service_date, DispatchTask.cancelled_at.is_(None))
        .order_by(DispatchTask.start_minute)
    )
    for task in tasks:
        alerts += _timing_alerts(
            status=task.status,
            start=task.start_minute,
            end=task.end_minute,
            now_minute=now_minute,
            label=f"Dispatch task #{task.id} ({task.kind.value.replace('_', ' ')})",
            who=task.driver.full_name,
            entity_type="dispatch_task",
            entity_id=task.id,
        )

    for trip in db.query(FieldTrip).filter(FieldTrip.status != TripStatus.COMPLETED):
        days = trip_windows(trip, padded=False)
        today_window = next(((s, e) for d, s, e in days if d == service_date), None)
        if today_window is None:
            continue
        label = f"Field trip #{trip.id} to {trip.destination}"
        departs_today = trip.departure_at.date() == service_date
        missing = [
            what
            for what, value in (
                ("driver", trip.assigned_driver_id),
                ("bus", trip.assigned_vehicle_id),
            )
            if value is None
        ]
        if departs_today and missing:
            alerts.append(
                Alert(
                    "unstaffed_trip",
                    CRITICAL,
                    f"{label} departs at {trip.departure_at.strftime('%H:%M')} "
                    f"with no {' or '.join(missing)} assigned",
                    "field_trip",
                    trip.id,
                    today_window[0],
                )
            )
        back = trip_return(trip)
        due_back_today = back.date() == service_date
        if (
            due_back_today
            and trip.actual_return_at is None
            and now_minute is not None
            and now_minute >= today_window[1] + FINISH_GRACE_MINUTES
        ):
            alerts.append(
                Alert(
                    "overdue_trip",
                    WARNING,
                    f"{label} was due back at {back.strftime('%H:%M')}; no return recorded",
                    "field_trip",
                    trip.id,
                    today_window[1],
                )
            )

    # Spec section 10: runs whose trip passes near a closure in force. Only
    # for today: that's what "in force" is about.
    if is_today:
        in_force = closures.active_now(db, now)
        for a in assignments:
            if a.status in TERMINAL:
                continue
            for impact in closures.impacts(db, a, in_force):
                label = f"{_run_label(a.run)} on {a.crew.vehicle.label}"
                what = closures.describe(impact.closure)
                if impact.stop_inside is not None:
                    alerts.append(
                        Alert(
                            "closure_at_stop",
                            CRITICAL,
                            f"The {impact.stop_inside} stop of {label} is inside a closure "
                            f"({what}): arrange another pick-up point",
                            "assignment",
                            a.id,
                            a.start_minute,
                        )
                    )
                else:
                    alerts.append(
                        Alert(
                            "road_closure",
                            WARNING,
                            f"{label} passes near a closure ({what}); its directions avoid it",
                            "assignment",
                            a.id,
                            a.start_minute,
                        )
                    )

    for vehicle in (
        db.query(Vehicle).filter(Vehicle.is_active.is_(True)).order_by(Vehicle.label).all()
    ):
        for severity, note in maintenance.due_notes(vehicle, service_date):
            alerts.append(Alert("vehicle_due", severity, note, "vehicle", vehicle.id))

    for report in (
        db.query(DriverReport)
        .filter(DriverReport.service_date == service_date)
        .order_by(DriverReport.created_at)
    ):
        if (
            report.report_type == DriverReportType.VEHICLE_DEFECT
            and report.status != DefectStatus.OPEN
        ):
            # Dealt with: the bus is out of service (its runs show "needs a
            # bus") or fixed.
            continue
        incident = report.report_type == DriverReportType.INCIDENT
        what = "Incident" if incident else "Vehicle defect"
        bus = f", {report.vehicle.label}" if report.vehicle is not None else ""
        text = (
            report.description
            if len(report.description) <= 140
            else (report.description[:137] + "...")
        )
        alerts.append(
            Alert(
                "incident" if incident else "vehicle_defect",
                CRITICAL if incident else WARNING,
                f"{what} reported by {report.driver.full_name}{bus}: {text}",
                "driver_report",
                report.id,
            )
        )

    alerts.sort(
        key=lambda a: (_SEVERITY_ORDER[a.severity], a.minute if a.minute is not None else 9999)
    )
    return DayAlerts(district_time=district_time, alerts=alerts)
