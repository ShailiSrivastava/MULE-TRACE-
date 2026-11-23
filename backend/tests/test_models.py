from collections.abc import Generator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.core.model_base import Base
from app.models import (
    Account,
    AnalysisJob,
    AuditLog,
    CaseAccount,
    CaseAlert,
    Dataset,
    DetectionAlert,
    GroundTruthLabel,
    InvestigationCase,
    RiskAssessment,
    Transaction,
    User,
)


@pytest.fixture
def model_session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def postgres_session() -> Generator[Session, None, None]:
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required for this precision integration test.")
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


def _make_accounts(session: Session, marker: str):
    user = User(email=f"analyst-{marker}@example.test", display_name="Analyst")
    session.add(user)
    session.flush()

    dataset = Dataset(
        owner_id=user.id,
        name=f"dataset-{marker}",
        status="ready",
        is_synthetic=True,
    )
    session.add(dataset)
    session.flush()

    sender = Account(
        dataset_id=dataset.id,
        external_id=f"sender-{marker}",
        account_type="business",
    )
    receiver = Account(
        dataset_id=dataset.id,
        external_id=f"receiver-{marker}",
        account_type="personal",
    )
    session.add_all([sender, receiver])
    session.flush()
    return user, dataset, sender, receiver


def _make_transaction(
    session: Session,
    dataset: Dataset,
    sender: Account,
    receiver: Account,
    *,
    external_id: str | None,
    occurred_at: datetime | None = None,
    amount: Decimal = Decimal("125.500000"),
) -> Transaction:
    transaction = Transaction(
        dataset_id=dataset.id,
        sender_account_id=sender.id,
        receiver_account_id=receiver.id,
        external_transaction_id=external_id,
        amount=amount,
        currency="USD",
        transaction_type="transfer",
        channel="wire",
        occurred_at=occurred_at or datetime(2026, 1, 1, tzinfo=UTC),
        metadata_json={"source": "test"},
    )
    session.add(transaction)
    session.flush()
    return transaction


def test_model_creation_relationships_and_ground_truth_separation(model_session):
    session = model_session
    user, dataset, sender, receiver = _make_accounts(session, "relationships")
    transaction = _make_transaction(
        session, dataset, sender, receiver, external_id="tx-one"
    )
    second_transaction = _make_transaction(
        session, dataset, sender, receiver, external_id="tx-two"
    )

    job = AnalysisJob(
        dataset_id=dataset.id,
        created_by_id=user.id,
        job_type="rule_scan",
        parameters={"ruleset": "test"},
    )
    session.add(job)
    session.flush()

    label = GroundTruthLabel(
        dataset_id=dataset.id,
        transaction_id=transaction.id,
        label_code="suspicious",
        source="synthetic",
        confidence=Decimal("0.9900"),
    )
    alert = DetectionAlert(
        dataset_id=dataset.id,
        analysis_job_id=job.id,
        transaction_id=transaction.id,
        rule_code="rapid_movement",
        title="Rapid movement pattern",
        score=Decimal("0.875000"),
        evidence={"window_minutes": 5},
    )
    risk = RiskAssessment(
        dataset_id=dataset.id,
        analysis_job_id=job.id,
        account_id=sender.id,
        score=Decimal("0.750000"),
        risk_level="high",
        rationale={"signal": "rapid movement"},
    )
    case = InvestigationCase(
        dataset_id=dataset.id,
        created_by_id=user.id,
        title="Review rapid movement",
        metadata_json={"priority_reason": "test"},
    )
    session.add_all([label, alert, risk, case])
    session.flush()

    account_link = CaseAccount(
        dataset_id=dataset.id,
        case_id=case.id,
        account_id=sender.id,
        added_by_id=user.id,
    )
    alert_link = CaseAlert(
        dataset_id=dataset.id,
        case_id=case.id,
        alert_id=alert.id,
    )
    audit = AuditLog(
        actor_user_id=user.id,
        event_type="case.created",
        entity_type="investigation_case",
        entity_id=case.id,
        details={"title": case.title},
    )
    session.add_all([account_link, alert_link, audit])
    session.flush()

    assert transaction.sender_account.id == sender.id
    assert transaction.receiver_account.id == receiver.id
    assert {item.id for item in dataset.transactions} == {
        transaction.id,
        second_transaction.id,
    }
    assert [item.id for item in job.detection_alerts] == [alert.id]
    assert [item.id for item in job.risk_assessments] == [risk.id]
    assert case.account_links[0].account.id == sender.id
    assert case.alert_links[0].alert.id == alert.id
    assert transaction.ground_truth_labels[0].label_code == "suspicious"
    assert transaction.detection_alerts[0].rule_code == "rapid_movement"
    assert GroundTruthLabel.__tablename__ != DetectionAlert.__tablename__
    assert audit.actor.id == user.id


def test_foreign_keys_reject_missing_and_cross_dataset_accounts(model_session):
    session = model_session
    _, first_dataset, _, first_receiver = _make_accounts(session, "fk-one")
    _, _, second_sender, _ = _make_accounts(session, "fk-two")

    bad_transaction = Transaction(
        dataset_id=first_dataset.id,
        sender_account_id=uuid4(),
        receiver_account_id=first_receiver.id,
        amount=Decimal("1.000000"),
        currency="USD",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add(bad_transaction)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    _, first_dataset, _, first_receiver = _make_accounts(session, "fk-three")
    _, _, second_sender, _ = _make_accounts(session, "fk-four")
    cross_dataset_transaction = Transaction(
        dataset_id=first_dataset.id,
        sender_account_id=second_sender.id,
        receiver_account_id=first_receiver.id,
        amount=Decimal("1.000000"),
        currency="USD",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add(cross_dataset_transaction)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_unique_constraints_for_users_and_dataset_accounts(model_session):
    session = model_session
    user, dataset, sender, _ = _make_accounts(session, "unique")

    session.add(User(email=user.email))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    user, dataset, sender, _ = _make_accounts(session, "unique-account")
    session.add(Account(dataset_id=dataset.id, external_id=sender.external_id))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_multiple_transactions_between_the_same_account_pair_are_supported(
    model_session,
):
    session = model_session
    _, dataset, sender, receiver = _make_accounts(session, "parallel")
    first = _make_transaction(session, dataset, sender, receiver, external_id="pair-1")
    second = _make_transaction(session, dataset, sender, receiver, external_id="pair-2")

    assert first.id != second.id
    assert first.sender_account_id == second.sender_account_id
    assert first.receiver_account_id == second.receiver_account_id
    assert len(sender.outgoing_transactions) == 2
    assert len(receiver.incoming_transactions) == 2


def test_transaction_amount_uses_fixed_decimal_precision():
    amount_column = Transaction.__table__.c.amount
    assert amount_column.type.precision == 20
    assert amount_column.type.scale == 6


def test_utc_datetime_normalizes_offsets_and_rejects_naive_values(model_session):
    session = model_session
    _, dataset, sender, receiver = _make_accounts(session, "timestamps")
    local_time = datetime(
        2026,
        3,
        4,
        9,
        30,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    transaction = _make_transaction(
        session,
        dataset,
        sender,
        receiver,
        external_id="utc-offset",
        occurred_at=local_time,
    )
    session.expire(transaction, ["occurred_at"])

    assert transaction.occurred_at == datetime(2026, 3, 4, 4, 0, tzinfo=UTC)
    assert transaction.occurred_at.tzinfo is UTC

    invalid = Transaction(
        dataset_id=dataset.id,
        sender_account_id=sender.id,
        receiver_account_id=receiver.id,
        amount=Decimal("1.000000"),
        currency="USD",
        occurred_at=datetime(2026, 3, 4, 9, 30),
    )
    session.add(invalid)
    with pytest.raises(StatementError, match="timezone-aware"):
        session.flush()
    session.rollback()


def test_case_deletion_cascades_membership_rows(model_session):
    session = model_session
    _, dataset, sender, receiver = _make_accounts(session, "case-cascade")
    transaction = _make_transaction(
        session, dataset, sender, receiver, external_id="case-cascade-tx"
    )
    job = AnalysisJob(dataset_id=dataset.id, job_type="rule_scan")
    session.add(job)
    session.flush()
    alert = DetectionAlert(
        dataset_id=dataset.id,
        analysis_job_id=job.id,
        transaction_id=transaction.id,
        rule_code="test_rule",
        title="Test alert",
    )
    case = InvestigationCase(dataset_id=dataset.id, title="Test case")
    session.add_all([alert, case])
    session.flush()
    session.add_all(
        [
            CaseAccount(dataset_id=dataset.id, case_id=case.id, account_id=sender.id),
            CaseAlert(dataset_id=dataset.id, case_id=case.id, alert_id=alert.id),
        ]
    )
    session.flush()
    case_id = case.id

    session.delete(case)
    session.flush()

    assert (
        session.scalar(
            select(func.count())
            .select_from(CaseAccount)
            .where(CaseAccount.case_id == case_id)
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(CaseAlert)
            .where(CaseAlert.case_id == case_id)
        )
        == 0
    )


def test_dataset_and_account_deletion_are_restricted_by_retained_records(model_session):
    session = model_session
    _, dataset, sender, receiver = _make_accounts(session, "restrict")
    _make_transaction(session, dataset, sender, receiver, external_id="restrict-tx")
    session.add(InvestigationCase(dataset_id=dataset.id, title="Retained case"))
    session.flush()

    session.delete(sender)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    _, dataset, _, _ = _make_accounts(session, "restrict-dataset")
    session.add(InvestigationCase(dataset_id=dataset.id, title="Retained case"))
    session.flush()
    session.delete(dataset)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


@pytest.mark.integration
def test_postgres_dataset_deletion_cascades_dataset_owned_rows(postgres_session):
    session = postgres_session
    _, dataset, sender, receiver = _make_accounts(session, uuid4().hex)
    _make_transaction(
        session, dataset, sender, receiver, external_id=f"cascade-{uuid4().hex}"
    )

    session.execute(delete(Dataset).where(Dataset.id == dataset.id))

    assert (
        session.scalar(
            select(func.count())
            .select_from(Account)
            .where(Account.dataset_id == dataset.id)
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.dataset_id == dataset.id)
        )
        == 0
    )


@pytest.mark.integration
def test_postgres_preserves_full_monetary_precision(postgres_session):
    session = postgres_session
    marker = uuid4().hex
    _, dataset, sender, receiver = _make_accounts(session, marker)
    expected = Decimal("12345678901234.123456")
    transaction = _make_transaction(
        session,
        dataset,
        sender,
        receiver,
        external_id=f"precision-{marker}",
        amount=expected,
    )
    session.expire(transaction, ["amount"])

    assert transaction.amount == expected
