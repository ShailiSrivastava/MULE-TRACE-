"""JWT access-token creation and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings

ALGORITHM = "HS256"
TOKEN_TYPE = "access"


class TokenConfigurationError(RuntimeError):
    """Raised when the environment does not provide a safe JWT secret."""


class InvalidAccessTokenError(ValueError):
    """Raised when an access token is expired or its claims are invalid."""


def _jwt_secret() -> str:
    secret = settings.JWT_SECRET_KEY
    if secret is None or len(secret.get_secret_value()) < 32:
        raise TokenConfigurationError(
            "Set JWT_SECRET_KEY to a randomly generated value of at least 32 characters."
        )
    return secret.get_secret_value()


def create_access_token(
    subject: UUID | str,
    *,
    expires_delta: timedelta | None = None,
) -> str:
    """Sign a short-lived access token with required identity and validation claims."""

    now = datetime.now(UTC)
    expires = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    claims = {
        "sub": str(subject),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": expires,
        "jti": str(uuid4()),
        "token_type": TOKEN_TYPE,
    }
    return jwt.encode(claims, _jwt_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> UUID:
    """Validate signature, algorithm, issuer, audience, time claims, and subject."""

    try:
        claims = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require": [
                    "sub",
                    "iss",
                    "aud",
                    "iat",
                    "nbf",
                    "exp",
                    "jti",
                    "token_type",
                ]
            },
        )
        if claims.get("token_type") != TOKEN_TYPE:
            raise InvalidAccessTokenError("Invalid token type.")
        return UUID(claims["sub"])
    except TokenConfigurationError:
        raise
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise InvalidAccessTokenError("Invalid access token.") from exc
