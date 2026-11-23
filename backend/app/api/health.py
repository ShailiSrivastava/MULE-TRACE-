"""Process liveness and dependency readiness endpoints."""

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import DatabaseNotConfiguredError, check_database_connection

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
def readiness_check() -> dict[str, object]:
    """Report readiness only when the configured database answers a query."""
    try:
        check_database_connection()
    except (DatabaseNotConfiguredError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=503,
            detail="The database is unavailable.",
        ) from exc

    return {"status": "ready", "checks": {"database": "ok"}}
