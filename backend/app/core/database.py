import logging
import re
import time
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.metrics import record_database_query
from app.core.model_base import Base

__all__ = [
    "Base",
    "DatabaseNotConfiguredError",
    "SessionLocal",
    "check_database_connection",
    "database_url",
    "engine",
    "get_db",
    "get_engine",
]

# Engine configuration: supports PostgreSQL and SQLite for local fallbacks.
database_url = settings.sqlalchemy_database_url
engine: Engine | None = None
if database_url is not None:
    connect_args = {}
    engine_options = {
        "echo": settings.DATABASE_ECHO,
        "pool_pre_ping": True,
    }
    if database_url.get_backend_name() == "sqlite":
        connect_args = {"check_same_thread": False}
    elif database_url.get_backend_name() == "postgresql":
        connect_args = {
            "connect_timeout": settings.DATABASE_CONNECT_TIMEOUT,
            "application_name": "muletrace-api",
        }
        if settings.DATABASE_SSLMODE is not None:
            connect_args["sslmode"] = settings.DATABASE_SSLMODE
        engine_options.update(
            {
                "pool_size": settings.DATABASE_POOL_SIZE,
                "max_overflow": settings.DATABASE_MAX_OVERFLOW,
                "pool_timeout": settings.DATABASE_POOL_TIMEOUT,
                "pool_recycle": settings.DATABASE_POOL_RECYCLE,
            }
        )

    engine = create_engine(
        database_url,
        connect_args=connect_args,
        **engine_options,
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)


def _install_query_observability(database_engine: Engine) -> None:
    """Count query time and log slow operations without SQL or parameters."""
    logger = logging.getLogger("muletrace.database")

    @event.listens_for(database_engine, "before_cursor_execute")
    def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        connection.info.setdefault("muletrace_query_started", []).append(time.perf_counter())

    def finish_query(connection, statement: str) -> None:
        starts = connection.info.get("muletrace_query_started", [])
        if not starts:
            return
        duration = time.perf_counter() - starts.pop()
        is_slow = duration * 1000 >= settings.SLOW_QUERY_THRESHOLD_MS
        record_database_query(duration, slow=is_slow)
        if is_slow:
            operation = re.search(
                r"\b(SELECT|INSERT|UPDATE|DELETE)\b", statement, re.IGNORECASE
            )
            logger.warning(
                "database.query.slow",
                extra={
                    "query_duration_ms": round(duration * 1000, 2),
                    "db_operation": operation.group(1).upper() if operation else "OTHER",
                },
            )

    @event.listens_for(database_engine, "after_cursor_execute")
    def after_cursor_execute(connection, cursor, statement, parameters, context, executemany):
        finish_query(connection, statement)

    @event.listens_for(database_engine, "handle_error")
    def failed_cursor_execute(exception_context) -> None:
        connection = exception_context.connection
        if connection is not None:
            starts = connection.info.get("muletrace_query_started", [])
            if starts:
                starts.pop()


if engine is not None:
    _install_query_observability(engine)


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a database operation is requested without credentials."""


def get_engine() -> Engine:
    """Return the configured engine or explain which database config is missing."""
    if engine is None:
        raise DatabaseNotConfiguredError(
            "Configure DATABASE_URL or both POSTGRES_USER and POSTGRES_PASSWORD."
        )
    return engine


def check_database_connection() -> None:
    """Raise if the configured database cannot execute a simple query."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))


def get_db() -> Generator[Session, None, None]:
    """Yield one request-scoped session and roll back failed work before closing."""
    get_engine()
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
