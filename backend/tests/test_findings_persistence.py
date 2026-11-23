"""Persistence, idempotency, scope, and lifecycle tests for findings."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_engine
from app.core.model_base import Base
from app.detection.models import (
    DetectionFinding as DetectionFindingResult,
)
from app.detection.models import (
    DetectionRunResult,
    create_finding,
)
from app.models import (
    Account,
    AnalysisJob,
    AuditLog,
    Dataset,
    DetectionFinding,
    FindingAccount,
    FindingObservation,
    FindingStatus,
    FindingStatusHistory,
    FindingTransaction,
    Transaction,
    User,
    UserRole,
)
from app.services.findings import (
    AnalysisJobNotFound,
    FindingReferenceError,
    InvalidFindingTransition,
    assign_finding,
    persist_detection_run,
    transition_finding_status,
)
from app.services.risk_scoring import calculate_and_persist_risk_scores

BASE_TIME = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest.fixture
def finding_db() -> Generator[dict, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(
            email=f"owner-{uuid4().hex}@example.com",
            password_hash="hash",
            role=UserRole.INVESTIGATOR.value,
        )
        investigator = User(
            email=f"investigator-{uuid4().hex}@example.com",
            password_hash="hash",
            role=UserRole.INVESTIGATOR.value,
        )
        inactive_investigator = User(
            email=f"inactive-{uuid4().hex}@example.com",
            password_hash="hash",
            role=UserRole.INVESTIGATOR.value,
            is_active=False,
        )
        other_owner = User(
            email=f"other-{uuid4().hex}@example.com", password_hash="hash"
        )
        db.add_all([owner, investigator, inactive_investigator, other_owner])
        db.flush()
        dataset = Dataset(owner_id=owner.id, name=f"Dataset {uuid4().hex}")
        other_dataset = Dataset(owner_id=other_owner.id, name=f"Other {uuid4().hex}")
        db.add_all([dataset, other_dataset])
        db.flush()
        accounts = [
            Account(dataset_id=dataset.id, external_id=f"acct-{uuid4().hex}")
            for _ in range(3)
        ]
        other_account = Account(
            dataset_id=other_dataset.id, external_id=f"other-{uuid4().hex}"
        )
        db.add_all([*accounts, other_account])
        db.flush()
        transactions = [
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[index].id,
                receiver_account_id=accounts[index + 1].id,
                amount="25.000000",
                currency="USD",
                occurred_at=BASE_TIME + timedelta(seconds=index),
            )
            for index in range(2)
        ]
        job = AnalysisJob(dataset_id=dataset.id, job_type="detection")
        second_job = AnalysisJob(dataset_id=dataset.id, job_type="detection")
        foreign_job = AnalysisJob(dataset_id=other_dataset.id, job_type="detection")
        db.add_all([*transactions, job, second_job, foreign_job])
        db.commit()
        for item in [owner, investigator, inactive_investigator, other_owner, dataset,
                     other_dataset, *accounts, other_account, *transactions, job,
                     second_job, foreign_job]:
            db.refresh(item)
        yield {
            "engine": engine,
            "factory": factory,
            "owner": owner,
            "investigator": investigator,
            "inactive_investigator": inactive_investigator,
            "other_owner": other_owner,
            "dataset": dataset,
            "other_dataset": other_dataset,
            "accounts": accounts,
            "other_account": other_account,
            "transactions": transactions,
            "job": job,
            "second_job": second_job,
            "foreign_job": foreign_job,
        }
    engine.dispose()


def _result(context: dict, *, evidence: dict | None = None) -> DetectionRunResult:
    dataset = context["dataset"]
    accounts = context["accounts"]
    transactions = context["transactions"]
    finding = create_finding(
        detector_name="multi_hop",
        detector_version="1.0",
        category="multi_hop_movement",
        severity="high",
        title="Multi-hop transaction movement",
        explanation="A directed path includes an intermediary account.",
        dataset_id=dataset.id,
        account_ids=tuple(item.id for item in accounts),
        transaction_ids=tuple(item.id for item in transactions),
        start_at=transactions[0].occurred_at,
        end_at=transactions[-1].occurred_at,
        evidence=evidence or {
            "transaction_ids": [str(item.id) for item in transactions],
            "currency": "USD",
        },
        parameters={"maximum_hops": 4},
        deduplication_context=tuple(str(item.id) for item in transactions),
    )
    return DetectionRunResult(
        dataset_id=dataset.id,
        findings=(finding,),
        executions=(),
    )


def _persist(context: dict, db: Session, result=None, *, job=None, observed_at=BASE_TIME):
    return persist_detection_run(
        db,
        dataset_id=context["dataset"].id,
        analysis_job_id=(job or context["job"]).id,
        actor=context["owner"],
        result=result or _result(context),
        observed_at=observed_at,
    )


def test_persistence_keeps_stable_id_multiple_relations_and_exact_snapshots(finding_db):
    context = finding_db
    with context["factory"]() as db:
        result = _result(context)
        persisted = _persist(context, db, result)
        finding = persisted.findings[0]

        assert persisted.created_count == 1
        assert finding.id == result.findings[0].finding_id
        assert finding.deduplication_key == result.findings[0].deduplication_key
        assert finding.status == FindingStatus.NEW.value
        assert finding.evidence == result.findings[0].evidence
        assert finding.parameters == result.findings[0].parameters
        assert db.scalar(
            select(func.count()).select_from(FindingAccount).where(
                FindingAccount.finding_id == finding.id
            )
        ) == 3
        assert db.scalar(
            select(func.count()).select_from(FindingTransaction).where(
                FindingTransaction.finding_id == finding.id
            )
        ) == 2
        observation = db.scalar(
            select(FindingObservation).where(FindingObservation.finding_id == finding.id)
        )
        assert observation is not None
        assert observation.evidence == result.findings[0].evidence
        assert observation.analysis_job_id == context["job"].id
        assert db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.entity_id == finding.id,
                AuditLog.event_type == "finding.created",
            )
        ) == 1


def test_repeated_analysis_is_idempotent_and_new_job_preserves_observations(finding_db):
    context = finding_db
    with context["factory"]() as db:
        first_result = _result(context)
        first = _persist(context, db, first_result, observed_at=BASE_TIME)
        first_last_detected = first.findings[0].last_detected_at
        repeated = _persist(
            context,
            db,
            first_result,
            observed_at=BASE_TIME + timedelta(hours=1),
        )
        assert repeated.unchanged_count == 1
        assert repeated.findings[0].last_detected_at == first_last_detected
        assert db.scalar(select(func.count()).select_from(FindingObservation)) == 1
        assert db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.event_type == "finding.created"
            )
        ) == 1

        next_result = _result(context, evidence={"repeated": True, "currency": "USD"})
        next_result = next_result.model_copy(
            update={"findings": (
            DetectionFindingResult(
                **{
                    **first_result.findings[0].model_dump(),
                    "evidence": next_result.findings[0].evidence,
                }
            ),
            )}
        )
        next_run = _persist(
            context,
            db,
            next_result,
            job=context["second_job"],
            observed_at=BASE_TIME + timedelta(days=1),
        )
        assert next_run.observed_count == 1
        assert next_run.findings[0].last_detected_at == BASE_TIME + timedelta(days=1)
        assert next_run.findings[0].status == FindingStatus.NEW.value
        assert next_run.findings[0].evidence == {"repeated": True, "currency": "USD"}
        snapshots = db.scalars(
            select(FindingObservation).where(
                FindingObservation.finding_id == next_run.findings[0].id
            )
        ).all()
        assert len(snapshots) == 2
        assert sorted(item.evidence["currency"] for item in snapshots) == ["USD", "USD"]
        assert any(item.evidence == {"repeated": True, "currency": "USD"} for item in snapshots)


def test_missing_cross_dataset_and_wrong_job_references_are_rejected(finding_db):
    context = finding_db
    with context["factory"]() as db:
        foreign_result = _result(context)
        foreign_finding = foreign_result.findings[0].model_copy(
            update={"account_ids": (*foreign_result.findings[0].account_ids, context["other_account"].id)}
        )
        foreign_result = foreign_result.model_copy(update={"findings": (foreign_finding,)})
        with pytest.raises(FindingReferenceError):
            _persist(context, db, foreign_result)
        assert db.scalar(select(func.count()).select_from(DetectionFinding)) == 0

        with pytest.raises(AnalysisJobNotFound):
            _persist(context, db, job=context["foreign_job"])
        assert db.scalar(select(func.count()).select_from(DetectionFinding)) == 0


def test_persistence_rolls_back_all_rows_when_a_flush_fails(finding_db):
    context = finding_db
    with context["factory"]() as db:
        def fail_flush(session, flush_context, instances):
            raise RuntimeError("synthetic database failure")

        event.listen(db, "before_flush", fail_flush, once=True)
        with pytest.raises(RuntimeError, match="synthetic database failure"):
            _persist(context, db)
        assert db.scalar(select(func.count()).select_from(DetectionFinding)) == 0
        assert db.scalar(select(func.count()).select_from(FindingObservation)) == 0
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_lifecycle_valid_transitions_reason_and_assignment_policy(finding_db):
    context = finding_db
    with context["factory"]() as db:
        persisted = _persist(context, db)
        finding = persisted.findings[0]
        moved = transition_finding_status(
            db,
            dataset_id=context["dataset"].id,
            finding_id=finding.id,
            actor=context["owner"],
            new_status=FindingStatus.REVIEWING,
            reason=None,
        )
        assert moved.status == FindingStatus.REVIEWING.value
        with pytest.raises(InvalidFindingTransition, match="reason is required"):
            transition_finding_status(
                db,
                dataset_id=context["dataset"].id,
                finding_id=finding.id,
                actor=context["owner"],
                new_status=FindingStatus.RESOLVED,
                reason=None,
            )
        resolved = transition_finding_status(
            db,
            dataset_id=context["dataset"].id,
            finding_id=finding.id,
            actor=context["owner"],
            new_status=FindingStatus.RESOLVED,
            reason="Reviewed the available transfer evidence.",
        )
        assert resolved.status == FindingStatus.RESOLVED.value
        assert db.scalar(
            select(func.count()).select_from(FindingStatusHistory).where(
                FindingStatusHistory.finding_id == finding.id
            )
        ) == 3

        assigned = assign_finding(
            db,
            dataset_id=context["dataset"].id,
            finding_id=finding.id,
            actor=context["owner"],
            assignee_id=context["investigator"].id,
        )
        assert assigned.assigned_to_id == context["investigator"].id
        with pytest.raises(ValueError, match="active investigator"):
            assign_finding(
                db,
                dataset_id=context["dataset"].id,
                finding_id=finding.id,
                actor=context["owner"],
                assignee_id=context["inactive_investigator"].id,
            )
        assert assigned.assigned_to_id == context["investigator"].id


@pytest.fixture
def postgres_session() -> Generator[Session, None, None]:
    try:
        engine = get_engine()
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL is unavailable ({type(exc).__name__}).")
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required for finding persistence integration.")
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.mark.integration
def test_postgres_persists_normalized_findings_and_observations(postgres_session):
    db = postgres_session
    marker = uuid4().hex
    owner = User(email=f"finding-pg-{marker}@example.com", password_hash="test-hash")
    db.add(owner)
    db.flush()
    dataset = Dataset(owner_id=owner.id, name=f"Finding PostgreSQL {marker}")
    db.add(dataset)
    db.flush()
    accounts = [
        Account(dataset_id=dataset.id, external_id=f"pg-{marker}-{index}")
        for index in range(3)
    ]
    db.add_all(accounts)
    db.flush()
    transactions = [
        Transaction(
            dataset_id=dataset.id,
            sender_account_id=accounts[index].id,
            receiver_account_id=accounts[index + 1].id,
            amount="12.340000",
            currency="USD",
            occurred_at=BASE_TIME + timedelta(seconds=index),
        )
        for index in range(2)
    ]
    job = AnalysisJob(dataset_id=dataset.id, job_type="detection")
    db.add_all([*transactions, job])
    db.flush()
    result_finding = create_finding(
        detector_name="multi_hop",
        detector_version="1.0",
        category="multi_hop_movement",
        severity="high",
        title="PostgreSQL test finding",
        explanation="A test path includes one intermediary account.",
        dataset_id=dataset.id,
        account_ids=tuple(item.id for item in accounts),
        transaction_ids=tuple(item.id for item in transactions),
        start_at=transactions[0].occurred_at,
        end_at=transactions[-1].occurred_at,
        evidence={"transaction_ids": [str(item.id) for item in transactions]},
        parameters={"max_hops": 4},
    )
    result = DetectionRunResult(
        dataset_id=dataset.id, findings=(result_finding,), executions=()
    )
    persisted = persist_detection_run(
        db,
        dataset_id=dataset.id,
        analysis_job_id=job.id,
        actor=owner,
        result=result,
        observed_at=BASE_TIME,
    )
    assert persisted.findings[0].id == result_finding.finding_id
    assert db.scalar(
        select(func.count()).select_from(FindingAccount).where(
            FindingAccount.finding_id == result_finding.finding_id
        )
    ) == 3
    assert db.scalar(
        select(func.count()).select_from(FindingTransaction).where(
            FindingTransaction.finding_id == result_finding.finding_id
        )
    ) == 2
    assessments, result = calculate_and_persist_risk_scores(
        db,
        dataset_id=dataset.id,
        analysis_job_id=job.id,
        actor=owner,
        assessed_at=BASE_TIME + timedelta(minutes=1),
    )
    assert len(assessments) == 4
    assert len(result.finding_scores) == 1
    assert len(result.account_scores) == 3
    assert all(row.score_components for row in assessments)
