"""Process liveness and dependency readiness endpoints."""

from fastapi import APIRouter, HTTPException
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import DatabaseNotConfiguredError, check_database_connection
from app.core.redis import check_redis_connection

router = APIRouter(tags=["Health"])


def _legacy_health_payload() -> dict[str, str]:
    """Keep the original health response available for existing clients."""
    return {
        "status": "healthy",
        "service": "muletrace-backend",
        "version": "0.1.0",
    }


@router.get("/health", summary="Legacy process health check")
def health_check() -> dict[str, str]:
    """Compatibility route retained as a process liveness check."""
    return _legacy_health_payload()


@router.get("/health/live", summary="Check that the API process is alive")
def liveness_check() -> dict[str, str]:
    """Report process liveness without depending on external services."""
    return _legacy_health_payload()


@router.get("/health/ready", summary="Check that required services are ready")
def readiness_check() -> dict[str, str]:
    """Report readiness without disclosing which internal dependency is failing."""
    try:
        check_database_connection()
        check_redis_connection()
    except (
        DatabaseNotConfiguredError,
        SQLAlchemyError,
        RedisError,
        OSError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail="The service is not ready.",
        ) from exc

    return {"status": "ready"}
