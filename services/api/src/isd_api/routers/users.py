from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from isd_api import account_emails, mailer, passwords
from isd_api.audit import record as record_audit
from isd_api.config import settings
from isd_api.db import get_db
from isd_api.models import Driver, Role, School, Student, User
from isd_api.schemas import ResetLinkRead, UserCreate, UserRead, UserUpdate
from isd_api.security import UNUSABLE_PASSWORD, get_current_user, hash_password, require_role

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> User:
    """spec section 17: user permissions are a Transportation
    Administrator responsibility. Without a password, the person is
    emailed a link to choose their own (Phase 5.2), so the admin never
    knows it."""
    if db.query(User).filter(User.email == payload.email).one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    if payload.password is None:
        if not mailer.is_configured():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email isn't set up here, so enter a password for the account",
            )
    else:
        problem = passwords.policy_problem(payload.password, payload.email)
        if problem is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problem)
    if payload.driver_id is not None and db.get(Driver, payload.driver_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    if payload.school_id is not None and db.get(School, payload.school_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")
    if payload.student_id is not None and db.get(Student, payload.student_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown student_id")

    user = User(
        email=payload.email,
        hashed_password=(
            UNUSABLE_PASSWORD if payload.password is None else hash_password(payload.password)
        ),
        full_name=payload.full_name,
        role=payload.role,
        driver_id=payload.driver_id,
        school_id=payload.school_id,
        student_id=payload.student_id,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That driver_id or student_id is already linked to another user",
        ) from exc
    record_audit(
        db,
        entity_type="user",
        entity_id=user.id,
        action="created",
        actor=current_user,
        after_state={
            "email": user.email,
            "role": user.role.value,
            "setup_email": payload.password is None,
        },
    )
    setup = None
    if payload.password is None:
        lifetime = timedelta(hours=settings.account_setup_link_hours)
        _, plain = passwords.issue_reset_token(db, user, current_user, lifetime)
        setup = account_emails.setup_email(user, plain, lifetime)
    db.commit()
    db.refresh(user)
    if setup is not None:
        background.add_task(mailer.send_quietly, setup)
    return user


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> list[User]:
    return list(db.query(User).order_by(User.id).all())


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> User:
    """spec section 17 "user permissions": reassign a role, relink a
    driver/school/student record, or deactivate an account. Deactivation
    takes effect immediately, not just on next login -- get_current_user
    checks User.is_active on every request, so an existing session's
    bearer token or cookie stops working on its very next use."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user_id == current_user.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )
    if payload.driver_id is not None and db.get(Driver, payload.driver_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown driver_id")
    if payload.school_id is not None and db.get(School, payload.school_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown school_id")
    if payload.student_id is not None and db.get(Student, payload.student_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown student_id")

    before_state = {
        "role": user.role.value,
        "is_active": user.is_active,
        "driver_id": user.driver_id,
        "school_id": user.school_id,
        "student_id": user.student_id,
    }
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.driver_id is not None:
        user.driver_id = payload.driver_id
    if payload.school_id is not None:
        user.school_id = payload.school_id
    if payload.student_id is not None:
        user.student_id = payload.student_id

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That driver_id or student_id is already linked to another user",
        ) from exc
    record_audit(
        db,
        entity_type="user",
        entity_id=user.id,
        action="updated",
        actor=current_user,
        before_state=before_state,
        after_state={
            "role": user.role.value,
            "is_active": user.is_active,
            "driver_id": user.driver_id,
            "school_id": user.school_id,
            "student_id": user.student_id,
        },
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-link", response_model=ResetLinkRead)
def issue_reset_link(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(Role.TRANSPORTATION_ADMIN)),
) -> ResetLinkRead:
    """A one-time link the admin passes on privately, so the person sets
    their own password; the admin never knows it. Shown once: only a
    hash of the token is kept (isd_api/passwords.py)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Reactivate the account first"
        )
    row, plain = passwords.issue_reset_token(db, user, current_user)
    # Read before commit: SQLite hands the value back without its time zone.
    expires_at = row.expires_at
    record_audit(
        db,
        entity_type="user",
        entity_id=user.id,
        action="reset_link_issued",
        actor=current_user,
        after_state={"expires_at": expires_at.isoformat()},
    )
    db.commit()
    return ResetLinkRead(reset_path=f"/reset-password#token={plain}", expires_at=expires_at)
