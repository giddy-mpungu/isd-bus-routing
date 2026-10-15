"""School bell schedules, the special-day calendar and the bus windows around
the bells (isd_api/bells.py has the decisions and the arithmetic).

Transportation administrators change them; dispatchers read them; a
school administrator reads their own school's. Every change brings the
routes that follow the bells, and their runs for today and later that
haven't started, up to date, and says how many moved."""

from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from isd_api import bells
from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import BellCalendarDay, BellSchedule, Role, School, User
from isd_api.schemas import (
    BellCalendarDayRead,
    BellCalendarSet,
    BellChange,
    BellImportRead,
    BellImportRequest,
    BellImportRow,
    BellOffsets,
    BellRulesRead,
    BellScheduleCreate,
    BellScheduleRead,
    BellScheduleUpdate,
    SchoolBellsRead,
    SchoolOffsetsUpdate,
)
from isd_api.security import require_role

router = APIRouter(tags=["bell-schedules"])

_ADMIN = Role.TRANSPORTATION_ADMIN
_READERS = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


def _offsets(o: bells.Offsets) -> BellOffsets:
    return BellOffsets(
        arrive_earliest_before=o.arrive_earliest_before,
        arrive_latest_before=o.arrive_latest_before,
        leave_earliest_after=o.leave_earliest_after,
        leave_latest_after=o.leave_latest_after,
    )


def _checked(payload: BellOffsets) -> bells.Offsets:
    offsets = bells.Offsets(**payload.model_dump())
    problem = bells.offsets_problem(offsets)
    if problem is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problem)
    return offsets


def _day_read(day: BellCalendarDay, school: School) -> BellCalendarDayRead:
    return BellCalendarDayRead(
        id=day.id,
        school_id=school.id,
        school_name=school.name,
        service_date=day.service_date,
        bell_schedule_id=day.bell_schedule_id,
        schedule_name=day.schedule.name,
    )


def _school(db: Session, school_id: int) -> School:
    school = db.get(School, school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="School not found")
    return school


def _schedule(db: Session, schedule_id: int) -> BellSchedule:
    schedule = db.get(BellSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bell schedule not found")
    return schedule


def _apply(db: Session, actor: User, school_ids: set[int] | None) -> BellChange:
    """Moves bell-following runs to the new bells, audits them, commits."""
    db.flush()
    moved = bells.refresh_windows(db, school_ids)
    bells.audit_moved_runs(db, moved, actor)
    db.commit()
    return BellChange(
        runs_updated=len(moved), assigned_runs_moved=sum(1 for m in moved if m.assigned)
    )


# --- The district's windows ------------------------------------------------


@router.get("/bell-rules", response_model=BellRulesRead)
def get_bell_rules(
    db: Session = Depends(get_db), _: User = Depends(require_role(*_READERS))
) -> BellRulesRead:
    offsets, is_default = bells.district_offsets(db)
    return BellRulesRead(**_offsets(offsets).model_dump(), is_default=is_default)


@router.put("/bell-rules", response_model=BellChange)
def put_bell_rules(
    payload: BellOffsets,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(_ADMIN)),
) -> BellChange:
    offsets = _checked(payload)
    before = _offsets(bells.district_offsets(db)[0]).model_dump()
    bells.save_district_offsets(db, offsets)
    record_audit(
        db,
        entity_type="bell_rules",
        entity_id=1,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state=payload.model_dump(),
    )
    # Schools with their own windows aren't affected, but refreshing them
    # changes nothing, so every school is simply checked.
    return _apply(db, current_user, None)


# --- One school ------------------------------------------------------------


@router.get("/schools/{school_id}/bells", response_model=SchoolBellsRead)
def get_school_bells(
    school_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_READERS, Role.SCHOOL_ADMIN)),
) -> SchoolBellsRead:
    if current_user.role == Role.SCHOOL_ADMIN and current_user.school_id != school_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only see your own school"
        )
    school = _school(db, school_id)
    days = (
        db.query(BellCalendarDay)
        .filter(
            BellCalendarDay.school_id == school.id,
            BellCalendarDay.service_date >= bells.district_today(db),
        )
        .order_by(BellCalendarDay.service_date)
        .all()
    )
    own = _offsets(bells.offsets_for(db, school)) if bells.school_has_own_offsets(school) else None
    return SchoolBellsRead(
        school_id=school.id,
        school_name=school.name,
        schedules=[BellScheduleRead.model_validate(s) for s in school.bell_schedules],
        own_offsets=own,
        offsets_in_use=_offsets(bells.offsets_for(db, school)),
        upcoming_days=[_day_read(d, school) for d in days],
    )


@router.put("/schools/{school_id}/bell-offsets", response_model=BellChange)
def put_school_offsets(
    school_id: int,
    payload: SchoolOffsetsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(_ADMIN)),
) -> BellChange:
    school = _school(db, school_id)
    offsets = _checked(payload.offsets) if payload.offsets is not None else None
    before = (
        _offsets(bells.offsets_for(db, school)).model_dump()
        if bells.school_has_own_offsets(school)
        else None
    )
    for field in (
        "arrive_earliest_before",
        "arrive_latest_before",
        "leave_earliest_after",
        "leave_latest_after",
    ):
        setattr(school, field, getattr(offsets, field) if offsets is not None else None)
    record_audit(
        db,
        entity_type="school",
        entity_id=school.id,
        action="bell_offsets_updated",
        actor=current_user,
        before_state={"offsets": before},
        after_state={"offsets": payload.offsets.model_dump() if payload.offsets else None},
    )
    return _apply(db, current_user, {school.id})


@router.post(
    "/schools/{school_id}/bell-schedules",
    response_model=BellScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_bell_schedule(
    school_id: int,
    payload: BellScheduleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(_ADMIN)),
) -> BellSchedule:
    school = _school(db, school_id)
    if any(s.name.lower() == payload.name.lower() for s in school.bell_schedules):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This school already has a schedule by that name",
        )
    # A school's first schedule is its regular one.
    regular = payload.is_regular or bells.regular_schedule(school) is None
    if regular:
        for other in school.bell_schedules:
            other.is_regular = False
    schedule = BellSchedule(
        school_id=school.id,
        name=payload.name,
        first_bell_minute=payload.first_bell_minute,
        dismissal_minute=payload.dismissal_minute,
        is_regular=regular,
    )
    db.add(schedule)
    db.flush()
    record_audit(
        db,
        entity_type="bell_schedule",
        entity_id=schedule.id,
        action="created",
        actor=current_user,
        after_state=BellScheduleRead.model_validate(schedule).model_dump(),
    )
    _apply(db, current_user, {school.id})
    db.refresh(schedule)
    return schedule


@router.patch("/bell-schedules/{schedule_id}", response_model=BellChange)
def update_bell_schedule(
    schedule_id: int,
    payload: BellScheduleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(_ADMIN)),
) -> BellChange:
    schedule = _schedule(db, schedule_id)
    school = schedule.school
    before = BellScheduleRead.model_validate(schedule).model_dump()
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is blank")
        if any(
            s.id != schedule.id and s.name.lower() == name.lower() for s in school.bell_schedules
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This school already has a schedule by that name",
            )
        schedule.name = name
    if payload.first_bell_minute is not None:
        schedule.first_bell_minute = payload.first_bell_minute
    if payload.dismissal_minute is not None:
        schedule.dismissal_minute = payload.dismissal_minute
    if schedule.first_bell_minute >= schedule.dismissal_minute:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The first bell must come before dismissal",
        )
    if payload.is_regular is not None:
        if not payload.is_regular and schedule.is_regular:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Make another schedule regular instead",
            )
        if payload.is_regular:
            for other in school.bell_schedules:
                other.is_regular = other.id == schedule.id
    record_audit(
        db,
        entity_type="bell_schedule",
        entity_id=schedule.id,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state=BellScheduleRead.model_validate(schedule).model_dump(),
    )
    return _apply(db, current_user, {school.id})


@router.delete("/bell-schedules/{schedule_id}", response_model=BellChange)
def delete_bell_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(_ADMIN)),
) -> BellChange:
    """An alternate only; the special days that used it go back to regular."""
    schedule = _schedule(db, schedule_id)
    if schedule.is_regular:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The regular schedule can't be deleted; make another one regular first",
        )
    school_id = schedule.school_id
    db.query(BellCalendarDay).filter(BellCalendarDay.bell_schedule_id == schedule.id).delete()
    record_audit(
        db,
        entity_type="bell_schedule",
        entity_id=schedule.id,
        action="deleted",
        actor=current_user,
        before_state=BellScheduleRead.model_validate(schedule).model_dump(),
    )
    db.delete(schedule)
    return _apply(db, current_user, {school_id})


# --- The calendar ----------------------------------------------------------


@router.get("/bell-calendar", response_model=list[BellCalendarDayRead])
def list_bell_calendar(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_READERS)),
) -> list[BellCalendarDayRead]:
    """Special days, from today on unless `from_date` says otherwise."""
    start = from_date or bells.district_today(db)
    query = db.query(BellCalendarDay, School).join(School, BellCalendarDay.school_id == School.id)
    query = query.filter(BellCalendarDay.service_date >= start)
    if to_date is not None:
        query = query.filter(BellCalendarDay.service_date <= to_date)
    rows = query.order_by(BellCalendarDay.service_date, School.name).all()
    return [_day_read(day, school) for day, school in rows]


@router.put("/bell-calendar", response_model=BellChange)
def set_bell_calendar(
    payload: BellCalendarSet,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(_ADMIN)),
) -> BellChange:
    """Use a named schedule on a date. Naming the regular schedule removes
    the special day (the date goes back to normal)."""
    if payload.school_ids is None:
        schools = db.query(School).order_by(School.name).all()
    else:
        schools = [_school(db, sid) for sid in payload.school_ids]
    wanted = payload.schedule_name.strip().lower()
    touched: set[int] = set()
    skipped: list[str] = []
    for school in schools:
        schedule = next((s for s in school.bell_schedules if s.name.lower() == wanted), None)
        if schedule is None:
            if payload.school_ids is not None:
                skipped.append(school.name)
            continue
        day = (
            db.query(BellCalendarDay)
            .filter(
                BellCalendarDay.school_id == school.id,
                BellCalendarDay.service_date == payload.service_date,
            )
            .one_or_none()
        )
        before = day.schedule.name if day is not None else None
        if schedule.is_regular:
            if day is not None:
                db.delete(day)
        elif day is None:
            db.add(
                BellCalendarDay(
                    school_id=school.id,
                    service_date=payload.service_date,
                    bell_schedule_id=schedule.id,
                )
            )
        else:
            day.bell_schedule_id = schedule.id
        record_audit(
            db,
            entity_type="school",
            entity_id=school.id,
            action="bell_calendar_set",
            actor=current_user,
            before_state={"date": payload.service_date.isoformat(), "schedule": before},
            after_state={"date": payload.service_date.isoformat(), "schedule": schedule.name},
        )
        touched.add(school.id)
    if not touched:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No school has a schedule by that name",
        )
    db.flush()
    db.expire_all()
    change = _apply(db, current_user, touched)
    return change.model_copy(update={"skipped_schools": skipped})


@router.delete("/bell-calendar/{day_id}", response_model=BellChange)
def delete_bell_calendar_day(
    day_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(_ADMIN)),
) -> BellChange:
    day = db.get(BellCalendarDay, day_id)
    if day is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Special day not found")
    school_id = day.school_id
    record_audit(
        db,
        entity_type="school",
        entity_id=school_id,
        action="bell_calendar_cleared",
        actor=current_user,
        before_state={"date": day.service_date.isoformat(), "schedule": day.schedule.name},
    )
    db.delete(day)
    db.flush()
    db.expire_all()
    return _apply(db, current_user, {school_id})


# --- CSV import ------------------------------------------------------------

_COLUMNS = ("school", "schedule", "first_bell", "dismissal")


def _minute(text: str) -> int:
    hours, _, minutes = text.strip().partition(":")
    value = int(hours) * 60 + int(minutes)
    if not (0 <= int(minutes) < 60 and 0 <= value < 1440):
        raise ValueError
    return value


@router.post("/bell-schedules/import", response_model=BellImportRead)
def import_bell_schedules(
    payload: BellImportRequest,
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(_ADMIN)),
) -> BellImportRead:
    """The district's bell list as CSV, with a header row:
    school, schedule, first_bell, dismissal (times as HH:MM, 24-hour).
    Schools are matched by name. A schedule named "Regular" is the
    school's regular one, as is a school's first schedule. With dry_run
    (the default) nothing is saved: the rows say what would happen."""
    reader = csv.DictReader(io.StringIO(payload.csv.lstrip("﻿")))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in _COLUMNS if c not in header]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The CSV needs these columns: {', '.join(_COLUMNS)}",
        )
    schools: dict[str, list[School]] = {}
    for s in db.query(School).all():
        schools.setdefault(s.name.strip().lower(), []).append(s)
    rows: list[BellImportRow] = []
    touched: set[int] = set()
    for line, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        school_name, name = row.get("school", ""), row.get("schedule", "")
        result = BellImportRow(line=line, school=school_name, schedule=name, outcome="error")
        rows.append(result)
        matches = schools.get(school_name.lower(), [])
        if not matches:
            result.message = "No school by that name"
            continue
        if len(matches) > 1:
            # Never guess which one: set these in Setup instead.
            result.message = "More than one school has that name; set its bells in Setup"
            continue
        school = matches[0]
        if not name or len(name) > 60:
            result.message = "The schedule needs a name of up to 60 characters"
            continue
        try:
            first, dismissal = _minute(row["first_bell"]), _minute(row["dismissal"])
        except (ValueError, KeyError):
            result.message = "Times must be HH:MM (24-hour)"
            continue
        if first >= dismissal:
            result.message = "The first bell must come before dismissal"
            continue
        existing = next((s for s in school.bell_schedules if s.name.lower() == name.lower()), None)
        if existing is not None:
            if (existing.first_bell_minute, existing.dismissal_minute) == (first, dismissal):
                result.outcome = "unchanged"
                continue
            result.outcome = "updated"
            if not dry_run:
                existing.first_bell_minute, existing.dismissal_minute = first, dismissal
        else:
            result.outcome = "created"
            if not dry_run:
                regular = name.lower() == "regular" or bells.regular_schedule(school) is None
                if regular:
                    for other in school.bell_schedules:
                        other.is_regular = False
                school.bell_schedules.append(
                    BellSchedule(
                        name=name,
                        first_bell_minute=first,
                        dismissal_minute=dismissal,
                        is_regular=regular,
                    )
                )
        touched.add(school.id)
    if dry_run:
        db.rollback()
        return BellImportRead(applied=False, rows=rows)
    record_audit(
        db,
        entity_type="bell_schedule",
        entity_id=0,
        action="imported",
        actor=current_user,
        after_state={
            "created": sum(1 for r in rows if r.outcome == "created"),
            "updated": sum(1 for r in rows if r.outcome == "updated"),
            "errors": sum(1 for r in rows if r.outcome == "error"),
        },
    )
    change = _apply(db, current_user, touched) if touched else None
    if change is None:
        db.commit()
    return BellImportRead(applied=True, rows=rows, change=change)
