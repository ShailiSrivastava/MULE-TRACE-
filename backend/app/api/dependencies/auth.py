"""Bearer token and role authorization dependencies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User, UserRole
from app.security.tokens import (
    InvalidAccessTokenError,
    TokenConfigurationError,
    decode_access_token,
)

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve a valid token to a currently active database user."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = decode_access_token(credentials.credentials)
    except TokenConfigurationError as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is not configured."
        ) from exc
    except InvalidAccessTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail="The access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active or user.password_hash is None:
        raise HTTPException(
            status_code=401,
            detail="The access token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*allowed_roles: UserRole) -> Callable:
    """Build a dependency that restricts an endpoint to selected roles."""

    def role_guard(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in {role.value for role in allowed_roles}:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return role_guard
