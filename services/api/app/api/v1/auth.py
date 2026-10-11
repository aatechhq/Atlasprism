"""Auth routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.api.deps import current_user
from app.models import User
from app.schemas.api import LoginRequest, TokenResponse, UserOut

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    # Same error for unknown email and wrong password: no account enumeration.
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise Unauthorized("Invalid email or password.")
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        expires_in_minutes=settings.jwt_expire_minutes,
    )


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
