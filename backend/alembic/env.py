from logging.config import fileConfig

from sqlalchemy.engine import Connection

from alembic import context
from app import models
from app.core.config import settings
from app.core.database import Base, get_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if models.User.metadata is not Base.metadata:
    raise RuntimeError(
        "MuleTrace models are not registered on the application metadata."
    )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating a DBAPI connection."""
    database_url = settings.sqlalchemy_database_url
    if database_url is None:
        raise RuntimeError(
            "Configure DATABASE_URL or both POSTGRES_USER and POSTGRES_PASSWORD."
        )

    url = database_url.render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using the application's configured SQLAlchemy engine."""
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return

    with get_engine().connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
