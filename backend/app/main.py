from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.v1.router import router as api_v1_router
from app.core import database
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.observability import RequestContextMiddleware, configure_logging
from app.core.redis import close_redis_client


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Release pooled database and Redis connections during graceful shutdown."""
    configure_logging(settings.LOG_LEVEL)
    try:
        yield
    finally:
        if database.engine is not None:
            database.engine.dispose()
        close_redis_client()


def create_app() -> FastAPI:
    """Build the API and register cross-cutting middleware and routers."""
    configure_logging(settings.LOG_LEVEL)
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="Backend API foundation for MuleTrace",
        version="0.1.0",
        debug=settings.DEBUG and settings.ENVIRONMENT.lower() == "development",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    register_exception_handlers(application)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Request-ID",
        ],
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.TRUSTED_HOSTS,
    )
    application.add_middleware(
        RequestContextMiddleware,
        max_request_body_bytes=settings.MAX_REQUEST_BODY_BYTES,
        production=settings.ENVIRONMENT == "production",
    )
    application.include_router(health_router)
    application.include_router(metrics_router)
    application.include_router(api_v1_router)

    @application.get("/", tags=["General"])
    def read_root() -> dict[str, str]:
        """Root endpoint providing service metadata."""
        return {
            "project": settings.PROJECT_NAME,
            "status": "online",
            "environment": settings.ENVIRONMENT,
            "docs_url": "/docs",
        }

    return application


app = create_app()
