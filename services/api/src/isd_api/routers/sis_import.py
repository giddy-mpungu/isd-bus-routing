"""SIS roster sync (spec section 19; ADR 0007: the SIS is authoritative for
student identity, name and school assignment; this system stays
authoritative for stop assignment and ridership, which are never touched).

Decision support, not silent automation (spec section 21): the default is
a dry run that reports exactly what would change, and anything the system
would have to guess about is reported for a human instead of applied --
an unmapped or ambiguous school, a possible duplicate of a hand-entered
student, a removal request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from isd_api import sis_sync
from isd_api.config import settings
from isd_api.db import get_db
from isd_api.integrations import oneroster_api
from isd_api.integrations.oneroster import MAX_BYTES, OneRosterFormatError, parse_students_csv
from isd_api.models import Role, SisSyncRun, User
from isd_api.schemas import SisImportResult, SisSyncRunRead, SisSyncStatus
from isd_api.security import require_role
from isd_api.sis_reconcile import reconcile

router = APIRouter(prefix="/integrations/sis", tags=["integrations"])


@router.post("/students/import", response_model=SisImportResult)
async def import_students(
    file: Annotated[UploadFile, File(description="OneRoster users.csv")],
    dry_run: Annotated[bool, Form()] = True,
    link_by_name: Annotated[bool, Form()] = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> SisImportResult:
    """Reconciles a OneRoster users.csv against the students table.

    link_by_name: a roster student with no match by SIS ID but the same
    name at the same school as exactly one hand-entered student (no SIS
    ID yet) is reported as needs_review by default; with link_by_name the
    SIS ID is attached to that existing student instead of creating a
    duplicate (ADR 0007's match-by-name-and-confirm for pre-integration
    data). The confirmation is the admin choosing to set the flag after
    reading the dry run."""
    raw = await file.read(MAX_BYTES + 1)
    try:
        parsed = parse_students_csv(raw)
    except OneRosterFormatError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return reconcile(db, parsed, dry_run=dry_run, link_by_name=link_by_name, actor=current_user)


@router.get("/sync", response_model=SisSyncStatus)
def sync_status(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> SisSyncStatus:
    """The scheduled OneRoster sync and its last 30 runs (isd_api/sis_sync.py)."""
    runs = db.query(SisSyncRun).order_by(SisSyncRun.id.desc()).limit(30).all()
    return SisSyncStatus(
        configured=oneroster_api.is_configured(),
        sync_time=settings.sis_sync_time,
        runs=[SisSyncRunRead.model_validate(r) for r in runs],
    )


@router.post("/sync", response_model=SisSyncRunRead)
def sync_now(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> SisSyncRunRead:
    """Runs the sync now, with the same rules as the nightly one: safe
    changes applied, the rest waiting for review."""
    if not oneroster_api.is_configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The SIS connection isn't set up; see docs/deployment.md, SIS sync",
        )
    try:
        run = sis_sync.run_sync(db, trigger="manual", actor=current_user)
    except sis_sync.SyncAlreadyRunning as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SisSyncRunRead.model_validate(run)
