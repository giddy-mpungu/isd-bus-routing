"""Operational reports and CSV export: see isd_api/reports.py."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from isd_api import reports
from isd_api.db import get_db
from isd_api.models import Role, User
from isd_api.schemas import ReportRead
from isd_api.security import require_role

router = APIRouter(prefix="/reports", tags=["reports"])

_READ_ROLES = (Role.TRANSPORTATION_ADMIN, Role.DISPATCHER)


def _build(db: Session, name: str, start: date, end: date) -> reports.Report:
    try:
        return reports.build(db, name, start, end)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown report"
        ) from None
    except reports.RangeError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.get("/{name}", response_model=ReportRead)
def get_report(
    name: str,
    start: date,
    end: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_READ_ROLES)),
) -> ReportRead:
    """The report for the page: its summary and the first rows."""
    report = _build(db, name, start, end)
    return ReportRead(
        name=report.name,
        title=report.title,
        start=start,
        end=end,
        columns=report.columns,
        rows=report.rows[: reports.PREVIEW_ROWS],
        total_rows=len(report.rows),
        summary=report.summary,
    )


@router.get("/{name}/csv")
def download_report_csv(
    name: str,
    start: date,
    end: date,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Every row, as a CSV download."""
    report = _build(db, name, start, end)
    filename = f"{report.name}_{start.isoformat()}_{end.isoformat()}.csv"
    return Response(
        # A byte-order mark so Excel reads the UTF-8 (names with accents).
        content="﻿" + reports.to_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
