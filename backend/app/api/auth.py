"""Public registration and login routes plus the protected current-user route."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import AuthRateLimit
from app.models import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.security.tokens import TokenConfigurationError, create_access_token
from app.services.auth import (
    DuplicateEmailError,
    authenticate_user,
    record_login_success,
    register_user,
)

router = APIRouter(tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an analyst account",
)
def register(
    payload: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
    _rate_limit: AuthRateLimit,
) -> User:
    """Create an active, least-privileged account with an Argon2 password hash."""

    try:
        return register_user(
            db,
            email=str(payload.email),
            password=payload.password.get_secret_value(),
            display_name=payload.display_name,
        )
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Exchange credentials for an access token",
)
def login(
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
    _rate_limit: AuthRateLimit,
) -> TokenResponse:
    """Authenticate credentials and return a signed short-lived access token."""

    user = authenticate_user(
        db,
        email=str(payload.email),
        password=payload.password.get_secret_value(),
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        token = create_access_token(user.id)
    except TokenConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured.",
        ) from exc

    record_login_success(db, user)
    return TokenResponse(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the current authenticated user",
)
def current_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Return the active user resolved from the bearer access token."""

    return user
