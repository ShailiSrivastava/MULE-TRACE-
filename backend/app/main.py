from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API foundation for MuleTrace",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["General"])
def read_root():
    """Root endpoint providing service metadata."""
    return {
        "project": settings.PROJECT_NAME,
        "status": "online",
        "environment": settings.ENVIRONMENT,
        "docs_url": "/docs",
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint for automated checks and monitoring."""
    return {
        "status": "healthy",
        "service": "muletrace-backend",
        "version": "0.1.0",
    }
