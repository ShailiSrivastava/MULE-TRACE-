from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import router as api_v1_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.observability import RequestContextMiddleware, configure_logging


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
    )

    register_exception_handlers(application)
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
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
