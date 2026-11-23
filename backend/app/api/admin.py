"""Administrator-only account activation and role management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_roles
from app.core.database import get_db
from app.core.rate_limit import SensitiveWriteRateLimit
from app.models import User, UserRole
from app.schemas.auth import ActivationUpdate, RoleUpdate, UserResponse
from app.services.auth import (
    AdministratorLockoutError,
    set_user_activation,
    set_user_role,
)

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.patch(
    "/users/{user_id}/activation",
    response_model=UserResponse,
    summary="Activate or deactivate a user",
)
def update_activation(
    user_id: UUID,
    payload: ActivationUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    _rate_limit: SensitiveWriteRateLimit,
) -> User:
    """Change account activation state; only an administrator may call this."""

    try:
        user = set_user_activation(
            db,
            target_user_id=user_id,
            is_active=payload.is_active,
            actor=actor,
        )
    except AdministratorLockoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.patch(
    "/users/{user_id}/role",
    response_model=UserResponse,
    summary="Change a user's role",
)
def update_role(
    user_id: UUID,
    payload: RoleUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    _rate_limit: SensitiveWriteRateLimit,
) -> User:
    """Change role only from a protected administrator workflow."""

    try:
        user = set_user_role(
            db,
            target_user_id=user_id,
            role=payload.role,
            actor=actor,
        )
    except AdministratorLockoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user
