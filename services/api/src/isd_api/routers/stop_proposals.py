"""Stop proposals (spec section 3.1): generate, then approve, reject or
relocate. Transportation admins only, since proposals are placed from
students' homes. See isd_api/stop_proposals.py for how they're made and
what they can't account for."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from isd_api import access_log, eligibility
from isd_api.audit import record as record_audit
from isd_api.db import get_db
from isd_api.models import (
    GeographicKnowledgeOverride,
    Role,
    School,
    Stop,
    StopProposal,
    StopProposalKind,
    StopProposalStatus,
    Student,
    StudentHome,
    User,
)
from isd_api.schemas import (
    GenerateStopProposals,
    StopProposalRead,
    StopProposalRider,
    StopProposalsGenerated,
    StopProposalUpdate,
)
from isd_api.security import require_role
from isd_api.stop_proposals import Hazard, Home, Place, hazard_warnings, propose

router = APIRouter(prefix="/stop-proposals", tags=["stop-proposals"])

_ADMIN = require_role(Role.TRANSPORTATION_ADMIN)


def _walk_limit(student: Student, rules: eligibility.Rules) -> float:
    band = eligibility.band_for(student)
    # No grade on record: the strictest non-specialized limit.
    if band is None:
        return min(v for b, v in rules.walk_miles.items() if b != eligibility.SPECIALIZED)
    return rules.walk_miles[band]


def _hazards(db: Session, school_id: int) -> list[Hazard]:
    rows = db.query(GeographicKnowledgeOverride).filter(
        (GeographicKnowledgeOverride.school_id.is_(None))
        | (GeographicKnowledgeOverride.school_id == school_id)
    )
    return [Hazard(r.category.value, r.note, r.location_lat, r.location_lon) for r in rows]


def _read(db: Session, proposal: StopProposal, rules: eligibility.Rules) -> StopProposalRead:
    students = {
        s.id: s for s in db.query(Student).filter(Student.id.in_(proposal.student_ids or [-1]))
    }
    homes = {
        h.student_id: h
        for h in db.query(StudentHome).filter(
            StudentHome.student_id.in_(proposal.student_ids or [-1])
        )
    }
    riders: list[StopProposalRider] = []
    warnings: list[str] = []
    for sid in proposal.student_ids:
        student = students.get(sid)
        if student is None:
            continue
        home = homes.get(sid)
        limit = _walk_limit(student, rules)
        walk = (
            None
            if home is None
            else eligibility.miles_between(
                home.location_lat, home.location_lon, proposal.location_lat, proposal.location_lon
            )
        )
        if walk is not None and walk > limit + 1e-9 and proposal.kind != StopProposalKind.CURB:
            warnings.append(f"{student.full_name} would walk {walk:.2f} mi (limit {limit:g} mi)")
        riders.append(
            StopProposalRider(
                student_id=sid,
                full_name=student.full_name,
                walk_miles=None if walk is None else round(walk, 2),
                walk_limit_miles=limit,
            )
        )
    if proposal.status == StopProposalStatus.PENDING and proposal.kind != StopProposalKind.EXISTING:
        spacing = rules.min_stop_spacing_miles
        for stop in db.query(Stop):
            miles = eligibility.miles_between(
                proposal.location_lat, proposal.location_lon, stop.location_lat, stop.location_lon
            )
            if miles < spacing:
                warnings.append(
                    f"{miles:.2f} mi from existing stop {stop.label} "
                    f"(the district's minimum spacing is {spacing:g} mi)"
                )
    warnings.extend(
        hazard_warnings(
            proposal.location_lat, proposal.location_lon, _hazards(db, proposal.school_id)
        )
    )
    return StopProposalRead(
        id=proposal.id,
        school_id=proposal.school_id,
        kind=proposal.kind,
        status=proposal.status,
        stop_id=proposal.stop_id,
        label=proposal.label,
        location_lat=proposal.location_lat,
        location_lon=proposal.location_lon,
        riders=riders,
        warnings=warnings,
        created_at=proposal.created_at,
        decided_at=proposal.decided_at,
    )


def _pending_or_409(db: Session, proposal_id: int) -> StopProposal:
    proposal = db.get(StopProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    if proposal.status != StopProposalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This proposal was already {proposal.status.value}",
        )
    return proposal


@router.post("/generate", response_model=StopProposalsGenerated)
def generate_stop_proposals(
    payload: GenerateStopProposals,
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
) -> StopProposalsGenerated:
    """Replaces the school's pending proposals with fresh ones, for its
    eligible students who have a home on file and no stop yet. Decided
    proposals are kept as history."""
    school = db.get(School, payload.school_id)
    if school is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")
    rules = eligibility.load_rules(db)
    students = (
        db.query(Student)
        .filter(Student.school_id == school.id, Student.withdrawn_on.is_(None))
        .order_by(Student.id)
        .all()
    )
    homes = {h.student_id: h for h in db.query(StudentHome)}

    counts = {"already_have_stop": 0, "no_home": 0, "not_eligible": 0}
    candidates: list[Home] = []
    for s in students:
        if s.stop_id is not None:
            counts["already_have_stop"] += 1
            continue
        home = homes.get(s.id)
        if home is None:
            counts["no_home"] += 1
            continue
        if not eligibility.eligibility_for(s, home, rules).eligible:
            counts["not_eligible"] += 1
            continue
        candidates.append(
            Home(
                student_id=s.id,
                lat=home.location_lat,
                lon=home.location_lon,
                walk_limit_miles=_walk_limit(s, rules),
                specialized=s.needs_specialized_transport,
            )
        )

    existing = [Place(p.id, p.label, p.location_lat, p.location_lon) for p in db.query(Stop)]
    made = propose(
        candidates,
        existing,
        min_spacing_miles=rules.min_stop_spacing_miles,
        hazards=_hazards(db, school.id),
    )

    db.query(StopProposal).filter(
        StopProposal.school_id == school.id, StopProposal.status == StopProposalStatus.PENDING
    ).delete(synchronize_session=False)
    rows = [
        StopProposal(
            school_id=school.id,
            kind=StopProposalKind(p.kind),
            stop_id=p.stop_id,
            label=p.label,
            location_lat=p.lat,
            location_lon=p.lon,
            student_ids=p.student_ids,
        )
        for p in made
    ]
    db.add_all(rows)
    db.flush()
    record_audit(
        db,
        entity_type="stop_proposals",
        entity_id=school.id,
        action="generated",
        actor=current_user,
        after_state={"proposals": len(rows), "students": len(candidates), **counts},
    )
    db.commit()
    return StopProposalsGenerated(
        proposals=[_read(db, r, rules) for r in rows],
        students_considered=len(candidates),
        **counts,
    )


@router.get("", response_model=list[StopProposalRead])
def list_stop_proposals(
    school_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
) -> list[StopProposalRead]:
    rules = eligibility.load_rules(db)
    rows = (
        db.query(StopProposal)
        .filter(StopProposal.school_id == school_id)
        .order_by(StopProposal.status != StopProposalStatus.PENDING, StopProposal.id)
        .all()
    )
    reads = [_read(db, r, rules) for r in rows]
    access_log.record_views(
        db, current_user, (rider.student_id for r in reads for rider in r.riders), "stop_proposals"
    )
    return reads


@router.patch("/{proposal_id}", response_model=StopProposalRead)
def update_stop_proposal(
    proposal_id: int,
    payload: StopProposalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
) -> StopProposalRead:
    """Relocate or rename a pending proposal before approving it."""
    proposal = _pending_or_409(db, proposal_id)
    moving = payload.location_lat is not None or payload.location_lon is not None
    if moving and proposal.kind == StopProposalKind.EXISTING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This proposal uses an existing stop; relocate that stop under Stops instead",
        )
    before = {
        "label": proposal.label,
        "location_lat": proposal.location_lat,
        "location_lon": proposal.location_lon,
    }
    if payload.label is not None and proposal.kind != StopProposalKind.EXISTING:
        proposal.label = payload.label
    if payload.location_lat is not None and payload.location_lon is not None:
        proposal.location_lat, proposal.location_lon = payload.location_lat, payload.location_lon
    db.flush()
    record_audit(
        db,
        entity_type="stop_proposal",
        entity_id=proposal.id,
        action="updated",
        actor=current_user,
        before_state=before,
        after_state={
            "label": proposal.label,
            "location_lat": proposal.location_lat,
            "location_lon": proposal.location_lon,
        },
    )
    db.commit()
    return _read(db, proposal, eligibility.load_rules(db))


@router.post("/{proposal_id}/approve", response_model=StopProposalRead)
def approve_stop_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
) -> StopProposalRead:
    """Creates the stop (unless it already exists) and assigns the
    proposal's students to it. A student given a stop since the proposal
    was made keeps theirs."""
    proposal = _pending_or_409(db, proposal_id)
    if proposal.kind == StopProposalKind.EXISTING:
        stop = db.get(Stop, proposal.stop_id)
        if stop is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="That stop no longer exists"
            )
    else:
        stop = Stop(
            label=proposal.label,
            location_lat=proposal.location_lat,
            location_lon=proposal.location_lon,
        )
        db.add(stop)
        db.flush()
        record_audit(
            db,
            entity_type="stop",
            entity_id=stop.id,
            action="created",
            actor=current_user,
            after_state={"label": stop.label, "from_proposal": proposal.id},
        )
    assigned = []
    for student in db.query(Student).filter(Student.id.in_(proposal.student_ids or [-1])):
        if student.stop_id is None:
            student.stop_id = stop.id
            assigned.append(student.id)
    proposal.status = StopProposalStatus.APPROVED
    proposal.stop_id = stop.id
    proposal.decided_at = datetime.now(UTC)
    proposal.decided_by_user_id = current_user.id
    db.flush()
    record_audit(
        db,
        entity_type="stop_proposal",
        entity_id=proposal.id,
        action="approved",
        actor=current_user,
        after_state={"stop_id": stop.id, "students_assigned": sorted(assigned)},
    )
    db.commit()
    return _read(db, proposal, eligibility.load_rules(db))


@router.post("/{proposal_id}/reject", response_model=StopProposalRead)
def reject_stop_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_ADMIN),
) -> StopProposalRead:
    proposal = _pending_or_409(db, proposal_id)
    proposal.status = StopProposalStatus.REJECTED
    proposal.decided_at = datetime.now(UTC)
    proposal.decided_by_user_id = current_user.id
    db.flush()
    record_audit(
        db,
        entity_type="stop_proposal",
        entity_id=proposal.id,
        action="rejected",
        actor=current_user,
    )
    db.commit()
    return _read(db, proposal, eligibility.load_rules(db))
