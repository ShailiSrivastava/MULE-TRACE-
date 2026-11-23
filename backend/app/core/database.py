from collections.abc import Generator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
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
    if database_url.get_backend_name() == "sqlite":
        connect_args = {"check_same_thread": False}

    engine = create_engine(
        database_url,
        echo=settings.DATABASE_ECHO,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)


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
