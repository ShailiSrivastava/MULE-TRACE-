"""Versioned API root and router registration point."""

from fastapi import APIRouter

from app.api.accounts import router as accounts_router
from app.api.admin import router as admin_router
from app.api.analysis import router as analysis_router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.cases import router as cases_router
from app.api.datasets import router as datasets_router
from app.api.findings import router as findings_router
from app.api.graph import router as graph_router
from app.api.imports import router as imports_router
from app.api.synthetic import router as synthetic_router
from app.api.transactions import router as transactions_router
from app.core.config import settings

router = APIRouter(prefix="/api/v1", tags=["API v1"])
router.include_router(auth_router, prefix="/auth")
router.include_router(cases_router)
router.include_router(datasets_router)
router.include_router(analytics_router)
router.include_router(graph_router)
router.include_router(imports_router)
router.include_router(accounts_router)
router.include_router(synthetic_router)
router.include_router(transactions_router)
router.include_router(findings_router)
router.include_router(analysis_router)
router.include_router(admin_router)


@router.get("", summary="Get version 1 API information")
def read_api_info() -> dict[str, str]:
    """Identify the active API contract version for clients."""
    return {
        "project": settings.PROJECT_NAME,
        "api_version": "v1",
        "status": "online",
    }
