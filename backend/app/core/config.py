from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILES = (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env")


class Settings(BaseSettings):
    """Application settings and environment configuration."""

    PROJECT_NAME: str = "MuleTrace API"
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False
    API_HOST: str = "127.0.0.1"
    API_PORT: int = Field(default=8000, ge=1, le=65535)
    PROXY_HEADERS_ENABLED: bool = False
    FORWARDED_ALLOW_IPS: str = "127.0.0.1"

    # CORS origins allowed to communicate with the API
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    TRUSTED_HOSTS: list[str] = ["localhost", "127.0.0.1", "testserver"]
    MAX_REQUEST_BODY_BYTES: int = Field(default=12_582_912, ge=1_024)
    METRICS_ENABLED: bool = False
    METRICS_TOKEN: SecretStr | None = None
    METRICS_TOKEN_FILE: str | None = None

    # Database connection parameters
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: SecretStr | None = None
    POSTGRES_PASSWORD_FILE: str | None = None
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "muletrace_dev"
    # An explicit URL takes precedence. When omitted, the URL is built from
    # the POSTGRES_* values below so changing one credential cannot leave a
    # stale DATABASE_URL behind.
    DATABASE_URL: SecretStr | None = None
    DATABASE_URL_FILE: str | None = None

    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DATABASE_MAX_OVERFLOW: int = Field(default=10, ge=0, le=100)
    DATABASE_POOL_TIMEOUT: int = Field(default=30, ge=1, le=300)
    DATABASE_POOL_RECYCLE: int = Field(default=1_800, ge=60, le=86_400)
    DATABASE_CONNECT_TIMEOUT: int = Field(default=5, ge=1, le=60)
    DATABASE_SSLMODE: Literal[
        "disable", "allow", "prefer", "require", "verify-ca", "verify-full"
    ] | None = None
    SLOW_QUERY_THRESHOLD_MS: int = Field(default=1_000, ge=1, le=60_000)
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Authentication secrets have no development or production code defaults.
    JWT_SECRET_KEY: SecretStr | None = None
    JWT_SECRET_KEY_FILE: str | None = None
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
    REDIS_PASSWORD_FILE: str | None = None
    CELERY_BROKER_URL: SecretStr | None = None
    CELERY_BROKER_URL_FILE: str | None = None
    REDIS_CONNECT_TIMEOUT: int = Field(default=2, ge=1, le=30)
    REDIS_SOCKET_TIMEOUT: int = Field(default=2, ge=1, le=30)
    AUTH_RATE_LIMIT_REQUESTS: int = Field(default=10, ge=1, le=1_000)
    AUTH_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1, le=3_600)
    CSV_UPLOAD_RATE_LIMIT_REQUESTS: int = Field(default=10, ge=1, le=100)
    CSV_UPLOAD_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=3_600, ge=60, le=86_400)

    ANALYSIS_MAX_ACTIVE_PER_DATASET: int = Field(default=1, ge=1, le=10)
    ANALYSIS_MAX_ACTIVE_PER_USER: int = Field(default=3, ge=1, le=100)
    ANALYSIS_MAX_RETRIES: int = Field(default=3, ge=0, le=10)
    ANALYSIS_TASK_SOFT_TIME_LIMIT: int = Field(default=3300, ge=30, le=86_400)
    ANALYSIS_TASK_TIME_LIMIT: int = Field(default=3600, ge=31, le=86_400)
    ANALYSIS_STALE_JOB_SECONDS: int = Field(default=3900, ge=60, le=172_800)
    ANALYSIS_BROKER_CONNECT_TIMEOUT: int = Field(default=2, ge=1, le=30)

    @model_validator(mode="before")
    @classmethod
    def load_secret_files(cls, values: object) -> object:
        """Read optional mounted Docker secrets without logging their contents."""
        if not isinstance(values, dict):
            return values
        sources = (
            ("POSTGRES_PASSWORD", "POSTGRES_PASSWORD_FILE"),
            ("DATABASE_URL", "DATABASE_URL_FILE"),
            ("JWT_SECRET_KEY", "JWT_SECRET_KEY_FILE"),
            ("REDIS_PASSWORD", "REDIS_PASSWORD_FILE"),
            ("CELERY_BROKER_URL", "CELERY_BROKER_URL_FILE"),
            ("METRICS_TOKEN", "METRICS_TOKEN_FILE"),
        )
        for value_name, file_name in sources:
            path = values.get(file_name)
            if values.get(value_name) or not path:
                continue
            try:
                secret_value = Path(str(path)).read_text(encoding="utf-8").strip()
            except OSError:
                raise ValueError(
                    f"Unable to read configured {file_name} secret file."
                ) from None
            if not secret_value:
                raise ValueError(f"Configured {file_name} secret file is empty.")
            values[value_name] = secret_value
        return values

    @model_validator(mode="after")
    def validate_analysis_timeouts(self) -> Settings:
        if self.ANALYSIS_TASK_SOFT_TIME_LIMIT >= self.ANALYSIS_TASK_TIME_LIMIT:
            raise ValueError("The analysis soft time limit must be less than its hard limit.")
        if self.ANALYSIS_STALE_JOB_SECONDS <= self.ANALYSIS_TASK_TIME_LIMIT:
            raise ValueError("The stale job timeout must exceed the task hard time limit.")
        if self.ENVIRONMENT != "production":
            return self

        problems: list[str] = []
        jwt_secret = (
            self.JWT_SECRET_KEY.get_secret_value() if self.JWT_SECRET_KEY else ""
        )
        if len(jwt_secret) < 48 or len(set(jwt_secret)) < 16:
            problems.append(
                "JWT_SECRET_KEY must contain at least 48 varied characters in production"
            )
        if self.DEBUG:
            problems.append("DEBUG must be false in production")
        if self.DATABASE_ECHO:
            problems.append("DATABASE_ECHO must be false in production")
        if self.LOG_LEVEL == "DEBUG":
            problems.append("LOG_LEVEL must not be DEBUG in production")
        if self.PROXY_HEADERS_ENABLED and (
            not self.FORWARDED_ALLOW_IPS.strip()
            or self.FORWARDED_ALLOW_IPS.strip() == "*"
        ):
            problems.append(
                "FORWARDED_ALLOW_IPS must list trusted proxy addresses explicitly"
            )
        if self.ACCESS_TOKEN_EXPIRE_MINUTES > 60:
            problems.append("ACCESS_TOKEN_EXPIRE_MINUTES must not exceed 60 in production")

        database_url = self.sqlalchemy_database_url
        if (
            database_url is None
            or database_url.get_backend_name() != "postgresql"
            or not database_url.username
            or not database_url.password
        ):
            problems.append(
                "Production requires PostgreSQL configured with an environment-based username and password"
            )
        elif len(database_url.password) < 24 or len(set(database_url.password)) < 12:
            problems.append(
                "The production PostgreSQL password must contain at least 24 varied characters"
            )

        broker_url = self.celery_broker_url
        try:
            redis_url = make_url(broker_url)
        except (TypeError, ValueError):
            redis_url = None
        if redis_url is None or redis_url.get_backend_name() != "redis":
            problems.append("Production requires a valid Redis broker URL")
        elif not redis_url.password:
            problems.append("Production Redis requires a password")
        elif len(redis_url.password) < 24 or len(set(redis_url.password)) < 12:
            problems.append(
                "The production Redis password must contain at least 24 varied characters"
            )

        if not self.TRUSTED_HOSTS or any(
            host.strip().lower() in {"", "localhost", "127.0.0.1", "testserver"}
            or "*" in host
            or any(character in host for character in "/?#@ ")
            for host in self.TRUSTED_HOSTS
        ):
            problems.append(
                "Production TRUSTED_HOSTS must contain explicit public host names"
            )
        if not self.CORS_ORIGINS or any(
            not _is_explicit_https_origin(origin) for origin in self.CORS_ORIGINS
        ):
            problems.append(
                "Production CORS_ORIGINS must contain explicit HTTPS origins"
            )
        if self.METRICS_ENABLED and (
            self.METRICS_TOKEN is None
            or len(self.METRICS_TOKEN.get_secret_value()) < 32
            or len(set(self.METRICS_TOKEN.get_secret_value())) < 12
        ):
            problems.append(
                "METRICS_TOKEN must be at least 32 characters when metrics are enabled"
            )
        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
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


def _is_explicit_https_origin(origin: str) -> bool:
    """Require a concrete HTTPS origin without paths or URL credentials."""
    if "*" in origin:
        return False
    try:
        parsed = urlsplit(origin)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and parsed.query == ""
        and parsed.fragment == ""
    )


settings = Settings()
