from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILES = (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env")


class Settings(BaseSettings):
    """Application settings and environment configuration."""

    PROJECT_NAME: str = "MuleTrace API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_HOST: str = "127.0.0.1"
    API_PORT: int = Field(default=8000, ge=1, le=65535)

    # CORS origins allowed to communicate with the API
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Database connection parameters
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: SecretStr | None = None
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "muletrace_dev"
    # An explicit URL takes precedence. When omitted, the URL is built from
    # the POSTGRES_* values below so changing one credential cannot leave a
    # stale DATABASE_URL behind.
    DATABASE_URL: SecretStr | None = None

    DATABASE_ECHO: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Authentication secrets have no development or production code defaults.
    JWT_SECRET_KEY: SecretStr | None = None
    JWT_ISSUER: str = "muletrace"
    JWT_AUDIENCE: str = "muletrace-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, gt=0, le=1440)

    # CSV uploads are read from framework-managed spooled files with hard limits.
    CSV_MAX_UPLOAD_BYTES: int = Field(default=10_485_760, ge=1_024)
    CSV_MAX_ROWS: int = Field(default=10_000, ge=1, le=100_000)

    # Celery uses the existing isolated Redis service; secrets stay in settings.
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = Field(default=6379, ge=1, le=65535)
    REDIS_DB: int = Field(default=0, ge=0, le=15)
    REDIS_PASSWORD: SecretStr | None = None
    CELERY_BROKER_URL: SecretStr | None = None

    ANALYSIS_MAX_ACTIVE_PER_DATASET: int = Field(default=1, ge=1, le=10)
    ANALYSIS_MAX_ACTIVE_PER_USER: int = Field(default=3, ge=1, le=100)
    ANALYSIS_MAX_RETRIES: int = Field(default=3, ge=0, le=10)
    ANALYSIS_TASK_SOFT_TIME_LIMIT: int = Field(default=3300, ge=30, le=86_400)
    ANALYSIS_TASK_TIME_LIMIT: int = Field(default=3600, ge=31, le=86_400)
    ANALYSIS_STALE_JOB_SECONDS: int = Field(default=3900, ge=60, le=172_800)
    ANALYSIS_BROKER_CONNECT_TIMEOUT: int = Field(default=2, ge=1, le=30)

    @model_validator(mode="after")
    def validate_analysis_timeouts(self) -> Settings:
        if self.ANALYSIS_TASK_SOFT_TIME_LIMIT >= self.ANALYSIS_TASK_TIME_LIMIT:
            raise ValueError("The analysis soft time limit must be less than its hard limit.")
        if self.ANALYSIS_STALE_JOB_SECONDS <= self.ANALYSIS_TASK_TIME_LIMIT:
            raise ValueError("The stale job timeout must exceed the task hard time limit.")
        return self

    model_config = SettingsConfigDict(
        # Root .env is the shared template; backend/.env may override it.
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def sqlalchemy_database_url(self) -> URL | None:
        """Return an explicit URL or compose one when credentials are configured."""
        if self.DATABASE_URL:
            return make_url(self.DATABASE_URL.get_secret_value())

        if not self.POSTGRES_USER or not self.POSTGRES_PASSWORD:
            return None

        return URL.create(
            drivername="postgresql+psycopg2",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )

    @property
    def celery_broker_url(self) -> str:
        """Build the Redis broker URL without placing credentials in source."""
        if self.CELERY_BROKER_URL:
            return self.CELERY_BROKER_URL.get_secret_value()
        credentials = (
            f":{quote(self.REDIS_PASSWORD.get_secret_value(), safe='')}@"
            if self.REDIS_PASSWORD
            else ""
        )
        return (
            f"redis://{credentials}{self.REDIS_HOST}:{self.REDIS_PORT}/"
            f"{self.REDIS_DB}"
        )


settings = Settings()
