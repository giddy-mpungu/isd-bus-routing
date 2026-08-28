from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from isd_api.db import get_db
from isd_api.models import User
from isd_api.schemas import Token
from isd_api.security import (
    clear_session_cookie,
    create_access_token,
    create_session_token,
    set_session_cookie,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    user = db.query(User).filter(User.email == form_data.username).one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(form_data.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Two independent tokens for two independent purposes (Phase 3
    # plan): a short-lived bearer token for API/script/Swagger use
    # (returned in the body, unchanged from before), and a longer-lived
    # session token for the browser (set as an httpOnly cookie, never
    # exposed in the response body — the frontend never touches it).
    bearer_token = create_access_token(user_id=user.id, role=user.role)
    session_token = create_session_token(user_id=user.id, role=user.role)
    set_session_cookie(response, session_token)
    return Token(access_token=bearer_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    """No auth required — clearing a cookie that may or may not exist
    is harmless, and the caller (browser) always wants this to succeed."""
    clear_session_cookie(response)
