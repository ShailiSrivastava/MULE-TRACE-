import json
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.core import database

SCHEMA_TABLES = {
    "accounts",
    "analysis_jobs",
    "audit_logs",
    "case_accounts",
    "case_alerts",
    "datasets",
    "detection_findings",
    "detection_alerts",
    "finding_accounts",
    "finding_observations",
    "finding_status_history",
    "finding_transactions",
    "ground_truth_labels",
    "investigation_cases",
    "import_jobs",
    "ml_model_registry",
    "risk_assessments",
    "transactions",
    "users",
}


class TrackingSession(Session):
    """Session that records lifecycle calls made by the dependency."""

    closed_by_dependency = False
    rollback_count = 0

    def close(self) -> None:
        self.closed_by_dependency = True
        super().close()

    def rollback(self) -> None:
        self.rollback_count += 1
        super().rollback()


@pytest.fixture
def sqlite_engine(monkeypatch: pytest.MonkeyPatch) -> Generator[Engine, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    factory = sessionmaker(bind=engine, class_=TrackingSession, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    yield engine
    engine.dispose()


def _alembic_config(connection=None) -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def test_database_connection_check_runs_select_one(sqlite_engine):
    database.check_database_connection()


def test_database_session_dependency_closes_session(sqlite_engine):
    dependency = database.get_db()
    session = next(dependency)

    assert session.execute(text("SELECT 1")).scalar_one() == 1

    dependency.close()

    assert session.closed_by_dependency


def test_database_session_dependency_rolls_back_and_closes_on_error(sqlite_engine):
    dependency = database.get_db()
    session = next(dependency)
    session.execute(text("SELECT 1"))

    with pytest.raises(RuntimeError, match="request failed"):
        dependency.throw(RuntimeError("request failed"))

    assert session.rollback_count == 1
    assert session.closed_by_dependency


def test_schema_migration_upgrades_from_baseline_and_rolls_back(sqlite_engine):
    with sqlite_engine.connect() as connection:
        config = _alembic_config(connection)
        command.upgrade(config, "19b6f8790061")
        legacy_id = uuid4().hex
        connection.execute(
            text("INSERT INTO users (id, email) VALUES (:id, :email)"),
            {"id": legacy_id, "email": "legacy@example.com"},
        )
        command.upgrade(config, "7e91c4ab2d60")
        dataset_id = uuid4().hex
        account_id = uuid4().hex
        job_id = uuid4().hex
        assessment_id = uuid4().hex
        connection.execute(
            text(
                "INSERT INTO datasets (id, owner_id, name, metadata) "
                "VALUES (:id, :owner, :name, '{}')"
            ),
            {"id": dataset_id, "owner": legacy_id, "name": "Existing data"},
        )
        connection.execute(
            text(
                "INSERT INTO accounts (id, dataset_id, external_id, metadata) "
                "VALUES (:id, :dataset, :external, '{}')"
            ),
            {"id": account_id, "dataset": dataset_id, "external": "legacy-account"},
        )
        connection.execute(
            text(
                "INSERT INTO analysis_jobs (id, dataset_id, job_type, parameters) "
                "VALUES (:id, :dataset, :type, '{}')"
            ),
            {"id": job_id, "dataset": dataset_id, "type": "legacy-analysis"},
        )
        connection.execute(
            text(
                "INSERT INTO risk_assessments "
                "(id, dataset_id, analysis_job_id, account_id, score, risk_level, rationale) "
                "VALUES (:id, :dataset, :job, :account, 0.250000, 'medium', '{}')"
            ),
            {
                "id": assessment_id,
                "dataset": dataset_id,
                "job": job_id,
                "account": account_id,
            },
        )
        command.upgrade(config, "head")
        command.upgrade(config, "head")

        assert set(inspect(connection).get_table_names()) == SCHEMA_TABLES | {
            "alembic_version"
        }
        transaction_indexes = {
            index["name"] for index in inspect(connection).get_indexes("transactions")
        }
        assert {
            "ix_transactions_dataset_amount",
            "ix_transactions_dataset_currency_occurred",
        } <= transaction_indexes
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "c7e4a91d2f60"
        )
        analysis_columns = {
            column["name"]
            for column in inspect(connection).get_columns("analysis_jobs")
        }
        assert {
            "progress_percent",
            "current_stage",
            "retry_count",
            "task_id",
            "idempotency_key",
            "cancel_requested_at",
            "heartbeat_at",
            "updated_at",
        } <= analysis_columns
        user_columns = {
            column["name"] for column in inspect(connection).get_columns("users")
        }
        assert {"password_hash", "role", "is_active"} <= user_columns
        risk_columns = {
            column["name"] for column in inspect(connection).get_columns("risk_assessments")
        }
        assert {
            "finding_id",
            "scoring_model_version",
            "score_components",
        } <= risk_columns
        legacy_user = connection.execute(
            text(
                "SELECT email, password_hash, role, is_active FROM users WHERE id = :id"
            ),
            {"id": legacy_id},
        ).one()
        assert legacy_user.email == "legacy@example.com"
        assert legacy_user.password_hash is None
        assert legacy_user.role == "ANALYST"
        assert bool(legacy_user.is_active)
        legacy_assessment = connection.execute(
            text(
                "SELECT dataset_id, account_id, finding_id, score, risk_level, "
                "scoring_model_version, score_components FROM risk_assessments WHERE id = :id"
            ),
            {"id": assessment_id},
        ).one()
        assert legacy_assessment.dataset_id == dataset_id
        assert legacy_assessment.account_id == account_id
        assert legacy_assessment.finding_id is None
        assert Decimal(str(legacy_assessment.score)) == Decimal("0.250000")
        assert legacy_assessment.risk_level == "medium"
        assert legacy_assessment.scoring_model_version == "legacy"
        assert json.loads(legacy_assessment.score_components) == {}

        command.downgrade(config, "7e91c4ab2d60")
        reverted_risk_columns = {
            column["name"]
            for column in inspect(connection).get_columns("risk_assessments")
        }
        assert "finding_id" not in reverted_risk_columns
        preserved_assessment = connection.execute(
            text(
                "SELECT dataset_id, account_id, score, risk_level FROM risk_assessments "
                "WHERE id = :id"
            ),
            {"id": assessment_id},
        ).one()
        assert preserved_assessment.dataset_id == dataset_id
        assert preserved_assessment.account_id == account_id
        assert Decimal(str(preserved_assessment.score)) == Decimal("0.250000")
        assert preserved_assessment.risk_level == "medium"

        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == SCHEMA_TABLES | {
            "alembic_version"
        }

        connection.execute(
            text("DELETE FROM risk_assessments WHERE id = :id"),
            {"id": assessment_id},
        )
        connection.execute(
            text("DELETE FROM datasets WHERE id = :id"), {"id": dataset_id}
        )
        connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": legacy_id})

        command.downgrade(config, "0001_empty_baseline")
        assert inspect(connection).get_table_names() == ["alembic_version"]
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "0001_empty_baseline"
        )

        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == SCHEMA_TABLES | {
            "alembic_version"
        }


@pytest.mark.integration
def test_configured_postgres_connection():
    if database.engine is None:
        pytest.skip("PostgreSQL credentials are not configured.")
    assert database.get_engine().dialect.name == "postgresql"

    database.check_database_connection()


@pytest.mark.integration
def test_postgres_schema_migration_is_repeatable():
    if database.engine is None:
        pytest.skip("PostgreSQL credentials are not configured.")
    if database.get_engine().dialect.name != "postgresql":
        pytest.skip("The configured database is not PostgreSQL.")

    config = _alembic_config()
    command.upgrade(config, "head")
    command.upgrade(config, "head")

    with database.get_engine().connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert tables == SCHEMA_TABLES | {"alembic_version"}
        assert (
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            == "c7e4a91d2f60"
        )
