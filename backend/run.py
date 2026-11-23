"""Run the development API using configured host and port values."""

import uvicorn

from app.core.config import settings


def main() -> None:
    """Start Uvicorn with the backend environment configuration."""
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.ENVIRONMENT == "development",
        log_level=settings.LOG_LEVEL.lower(),
        access_log=False,
        proxy_headers=settings.PROXY_HEADERS_ENABLED,
        forwarded_allow_ips=settings.FORWARDED_ALLOW_IPS,
    )


if __name__ == "__main__":
    main()
