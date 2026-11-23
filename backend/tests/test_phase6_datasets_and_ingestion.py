from __future__ import annotations

import csv
from collections.abc import Generator
from decimal import Decimal
from io import BytesIO, StringIO
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db, get_engine
from app.core.model_base import Base
from app.main import app
from app.models import (
    Account,
    AuditLog,
    Dataset,
    DetectionAlert,
    GroundTruthLabel,
    ImportJob,
    Transaction,
    User,
)
from app.schemas.synthetic import SyntheticGenerationRequest
from app.security.tokens import create_access_token
from app.services.csv_ingestion import import_accounts_csv, import_transactions_csv
from app.services.synthetic_data import build_synthetic_records

TEST_JWT_SECRET = "phase-six-test-jwt-secret-with-at-least-32-bytes"
TEST_PASSWORD_HASH = "phase-six-test-password-hash"
START_AT = "2026-10-15T00:00:00+00:00"
END_AT = "2026-10-16T00:00:00+00:00"


@pytest.fixture
def phase6_context(monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
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

    def override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(TEST_JWT_SECRET))
    monkeypatch.setattr(settings, "CSV_MAX_UPLOAD_BYTES", 10_485_760)
    monkeypatch.setattr(settings, "CSV_MAX_ROWS", 10_000)

    owner = User(email="phase6-owner@example.com", password_hash=TEST_PASSWORD_HASH)
    other_user = User(
        email="phase6-other@example.com", password_hash=TEST_PASSWORD_HASH
    )
    with factory() as db:
        db.add_all([owner, other_user])
        db.flush()
        primary_dataset = Dataset(owner_id=owner.id, name="Primary")
        empty_dataset = Dataset(owner_id=owner.id, name="Synthetic target")
        other_dataset = Dataset(owner_id=other_user.id, name="Other user's data")
        db.add_all([primary_dataset, empty_dataset, other_dataset])
        db.flush()
        sender = Account(
            dataset_id=primary_dataset.id,
            external_id="sender-001",
            account_type="business",
        )
        receiver = Account(
            dataset_id=primary_dataset.id,
            external_id="receiver-001",
            account_type="personal",
        )
        other_account = Account(
            dataset_id=other_dataset.id,
            external_id="other-001",
        )
        db.add_all([sender, receiver, other_account])
        db.commit()
        for entity in (
            owner,
            other_user,
            primary_dataset,
            empty_dataset,
            other_dataset,
            sender,
            receiver,
            other_account,
        ):
            db.refresh(entity)

    with TestClient(app) as client:
        yield {
            "client": client,
            "factory": factory,
            "owner": owner,
            "other_user": other_user,
            "primary_dataset": primary_dataset,
            "empty_dataset": empty_dataset,
            "other_dataset": other_dataset,
            "sender": sender,
            "receiver": receiver,
            "other_account": other_account,
            "owner_headers": {
                "Authorization": f"Bearer {create_access_token(owner.id)}"
            },
            "other_headers": {
                "Authorization": f"Bearer {create_access_token(other_user.id)}"
            },
        }
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _accounts_path() -> str:
    return "/api/v1/datasets"


def _account_import_path(dataset_id: UUID) -> str:
    return f"/api/v1/datasets/{dataset_id}/imports/accounts"


def _transaction_import_path(dataset_id: UUID) -> str:
    return f"/api/v1/datasets/{dataset_id}/imports/transactions"


def _csv(headers: list[str], rows: list[list[str]]) -> str:
    stream = StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue()


def _upload(client, path, headers, content: str, filename="records.csv"):
    return client.post(
        path,
        headers=headers,
        files={"file": (filename, content.encode("utf-8"), "application/octet-stream")},
    )


def test_dataset_lifecycle_scoping_counts_updates_and_audit(phase6_context):
    context = phase6_context
    client = context["client"]

    created = client.post(
        _accounts_path(),
        headers=context["owner_headers"],
        json={
            "name": "  New dataset  ",
            "description": "  Investigator upload  ",
            "source": "case-file",
            "metadata": {"case": "CASE-10"},
        },
    )
    assert created.status_code == 201
    dataset = created.json()
    assert dataset["name"] == "New dataset"
    assert dataset["description"] == "Investigator upload"
    assert dataset["account_count"] == dataset["transaction_count"] == 0
    assert "owner_id" not in dataset

    retrieved = client.get(
        f"{_accounts_path()}/{dataset['id']}", headers=context["owner_headers"]
    )
    assert retrieved.status_code == 200
    updated = client.patch(
        f"{_accounts_path()}/{dataset['id']}",
        headers=context["owner_headers"],
        json={"name": "New dataset v2", "metadata": {"reviewed": True}},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "New dataset v2"
    assert updated.json()["metadata"] == {"reviewed": True}

    listed = client.get(
        _accounts_path(),
        headers=context["owner_headers"],
        params={"page": 1, "page_size": 1},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 3
    assert listed.json()["total_pages"] == 3

    other_user_read = client.get(
        f"{_accounts_path()}/{dataset['id']}", headers=context["other_headers"]
    )
    other_user_list = client.get(_accounts_path(), headers=context["other_headers"])
    assert other_user_read.status_code == 404
    assert other_user_list.json()["total"] == 1
    assert all(
        item["id"] == str(context["other_dataset"].id)
        for item in other_user_list.json()["items"]
    )

    protected = client.patch(
        f"{_accounts_path()}/{dataset['id']}",
        headers=context["owner_headers"],
        json={"owner_id": str(context["other_user"].id), "status": "ready"},
    )
    assert protected.status_code == 422
    invalid_metadata = client.post(
        _accounts_path(),
        headers=context["owner_headers"],
        json={"name": "x" * 201},
    )
    assert invalid_metadata.status_code == 422

    with context["factory"]() as db:
        events = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == UUID(dataset["id"]),
                AuditLog.entity_type == "dataset",
            )
        ).all()
    assert {event.event_type for event in events} == {
        "dataset.created",
        "dataset.updated",
    }
    assert all("New dataset" not in str(event.details) for event in events)


def test_synthetic_generation_is_seeded_and_labels_remain_ground_truth(phase6_context):
    context = phase6_context
    request = SyntheticGenerationRequest(
        account_count=6,
        transaction_count=30,
        start_at=START_AT,
        end_at=END_AT,
        currencies=["usd", "EUR"],
        seed=20261123,
    )
    records_a = build_synthetic_records(context["empty_dataset"].id, request)
    records_b = build_synthetic_records(context["empty_dataset"].id, request)
    assert records_a == records_b
    assert len(records_a.accounts) == 6
    assert len(records_a.transactions) == 30

    response = context["client"].post(
        f"/api/v1/datasets/{context['empty_dataset'].id}/synthetic-data",
        headers=context["owner_headers"],
        json=request.model_dump(mode="json"),
    )
    assert response.status_code == 201
    result = response.json()
    assert result["seed"] == 20261123
    assert result["account_count"] == 6
    assert result["transaction_count"] == 30
    assert result["ground_truth_label_count"] == 22
    assert result["normal_transaction_count"] == 8

    with context["factory"]() as db:
        labels = db.scalars(
            select(GroundTruthLabel).where(
                GroundTruthLabel.dataset_id == context["empty_dataset"].id
            )
        ).all()
        detections = db.scalar(
            select(func.count(DetectionAlert.id)).where(
                DetectionAlert.dataset_id == context["empty_dataset"].id
            )
        )
        repeated_pair = db.execute(
            select(Transaction.sender_account_id, Transaction.receiver_account_id)
            .where(Transaction.dataset_id == context["empty_dataset"].id)
            .group_by(Transaction.sender_account_id, Transaction.receiver_account_id)
            .having(func.count(Transaction.id) > 1)
        ).first()
        generated_dataset = db.get(Dataset, context["empty_dataset"].id)
    assert labels
    assert all(label.source == "synthetic" for label in labels)
    assert all(label.label_scheme == "muletrace_synthetic_v1" for label in labels)
    assert detections == 0
    assert repeated_pair is not None
    assert generated_dataset.is_synthetic is True

    conflict = context["client"].post(
        f"/api/v1/datasets/{context['empty_dataset'].id}/synthetic-data",
        headers=context["owner_headers"],
        json=request.model_dump(mode="json"),
    )
    assert conflict.status_code == 409


def test_synthetic_generation_validates_limits_and_dataset_ownership(phase6_context):
    context = phase6_context
    invalid_request = context["client"].post(
        f"/api/v1/datasets/{context['empty_dataset'].id}/synthetic-data",
        headers=context["owner_headers"],
        json={
            "account_count": 4,
            "transaction_count": 22,
            "start_at": START_AT,
            "end_at": END_AT,
            "patterns": ["fan_in"],
        },
    )
    assert invalid_request.status_code == 422

    cross_user = context["client"].post(
        f"/api/v1/datasets/{context['empty_dataset'].id}/synthetic-data",
        headers=context["other_headers"],
        json={
            "account_count": 5,
            "transaction_count": 22,
            "start_at": START_AT,
            "end_at": END_AT,
        },
    )
    assert cross_user.status_code == 404


def test_account_csv_import_is_atomic_tracked_and_idempotent(phase6_context):
    context = phase6_context
    dataset_id = context["empty_dataset"].id
    contents = _csv(
        [
            "external_id",
            "account_type",
            "institution_code",
            "country_code",
            "metadata_json",
        ],
        [
            ["csv-acct-1", "business", "BANK-1", "us", '{"source":"file"}'],
            ["csv-acct-2", "personal", "BANK-2", "gb", ""],
        ],
    )

    first = _upload(
        context["client"],
        _account_import_path(dataset_id),
        context["owner_headers"],
        contents,
        filename="../../accounts.csv",
    )
    assert first.status_code == 200
    result = first.json()
    assert result["status"] == "completed"
    assert result["original_filename"] == "accounts.csv"
    assert result["total_rows"] == 2
    assert result["accepted_rows"] == 2
    assert result["rejected_rows"] == 0
    assert result["row_errors"] == []
    with context["factory"]() as db:
        imported_account = db.scalar(
            select(Account).where(
                Account.dataset_id == dataset_id,
                Account.external_id == "csv-acct-1",
            )
        )
    assert imported_account.metadata_json["muletrace_import"]["job_id"] == result["id"]
    assert imported_account.metadata_json["source"] == "file"

    retry = _upload(
        context["client"],
        _account_import_path(dataset_id),
        context["owner_headers"],
        contents,
    )
    assert retry.status_code == 200
    assert retry.json()["accepted_rows"] == 0
    assert retry.json()["duplicate_rows"] == 2
    assert retry.json()["skipped_rows"] == 2

    detail = context["client"].get(
        f"/api/v1/datasets/{dataset_id}/imports/{result['id']}",
        headers=context["owner_headers"],
    )
    listing = context["client"].get(
        f"/api/v1/datasets/{dataset_id}/imports",
        headers=context["owner_headers"],
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == result["id"]
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    with context["factory"]() as db:
        assert (
            db.scalar(
                select(func.count(Account.id)).where(Account.dataset_id == dataset_id)
            )
            == 2
        )
        events = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "import_job",
                AuditLog.entity_id.in_([UUID(result["id"]), UUID(retry.json()["id"])]),
            )
        ).all()
    assert {event.event_type for event in events} == {"dataset.import.completed"}


def test_csv_missing_headers_row_validation_and_atomic_rollback(phase6_context):
    context = phase6_context
    dataset_id = context["empty_dataset"].id
    path = _account_import_path(dataset_id)

    missing_header = _upload(
        context["client"],
        path,
        context["owner_headers"],
        "id,name\na,b\n",
    )
    assert missing_header.status_code == 200
    assert missing_header.json()["status"] == "failed"
    assert missing_header.json()["row_errors"][0]["row"] == 1

    partial = _csv(
        ["external_id", "country_code"],
        [["would-be-rolled-back", "US"], ["invalid-country", "USA"]],
    )
    failed = _upload(context["client"], path, context["owner_headers"], partial)
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["accepted_rows"] == 0
    assert failed.json()["rejected_rows"] == 1
    assert failed.json()["skipped_rows"] == 1
    assert "atomic_batch_rolled_back" in {
        error["code"] for error in failed.json()["row_errors"]
    }
    with context["factory"]() as db:
        assert (
            db.scalar(
                select(func.count(Account.id)).where(Account.dataset_id == dataset_id)
            )
            == 0
        )

    failed_jobs = context["client"].get(
        f"/api/v1/datasets/{dataset_id}/imports?status=failed",
        headers=context["owner_headers"],
    )
    completed_jobs = context["client"].get(
        f"/api/v1/datasets/{dataset_id}/imports?status=completed",
        headers=context["owner_headers"],
    )
    invalid_status = context["client"].get(
        f"/api/v1/datasets/{dataset_id}/imports?status=unknown",
        headers=context["owner_headers"],
    )
    assert failed_jobs.status_code == 200
    assert failed_jobs.json()["total"] == 2
    assert completed_jobs.status_code == 200
    assert completed_jobs.json()["total"] == 0
    assert invalid_status.status_code == 422


def test_transaction_csv_validation_unknown_accounts_and_duplicate_retry(
    phase6_context,
):
    context = phase6_context
    dataset_id = context["primary_dataset"].id
    valid = _csv(
        [
            "external_transaction_id",
            "sender_external_id",
            "receiver_external_id",
            "amount",
            "currency",
            "occurred_at",
            "transaction_type",
            "channel",
            "status",
            "metadata_json",
        ],
        [
            [
                "csv-tx-1",
                "sender-001",
                "receiver-001",
                "1.123456",
                "usd",
                "2026-10-15T10:00:00+05:30",
                "transfer",
                "wire",
                "settled",
                '{"memo":"one"}',
            ],
            [
                "csv-tx-2",
                "sender-001",
                "receiver-001",
                "2.000001",
                "EUR",
                "2026-10-15T10:01:00Z",
                "transfer",
                "wire",
                "settled",
                "",
            ],
        ],
    )
    first = _upload(
        context["client"],
        _transaction_import_path(dataset_id),
        context["owner_headers"],
        valid,
    )
    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert first.json()["accepted_rows"] == 2
    with context["factory"]() as db:
        imported_transaction = db.scalar(
            select(Transaction).where(
                Transaction.dataset_id == dataset_id,
                Transaction.external_transaction_id == "csv-tx-1",
            )
        )
    assert (
        imported_transaction.metadata_json["muletrace_import"]["job_id"]
        == first.json()["id"]
    )

    retry = _upload(
        context["client"],
        _transaction_import_path(dataset_id),
        context["owner_headers"],
        valid,
    )
    assert retry.json()["accepted_rows"] == 0
    assert retry.json()["duplicate_rows"] == 2

    invalid = _csv(
        [
            "external_transaction_id",
            "sender_external_id",
            "receiver_external_id",
            "amount",
            "currency",
            "occurred_at",
        ],
        [
            [
                "bad-amount",
                "sender-001",
                "receiver-001",
                "0",
                "USD",
                "2026-10-15T00:00:00Z",
            ],
            [
                "bad-currency",
                "sender-001",
                "receiver-001",
                "10",
                "US1",
                "2026-10-15T00:00:00Z",
            ],
            [
                "bad-time",
                "sender-001",
                "receiver-001",
                "10",
                "USD",
                "2026-10-15T00:00:00",
            ],
            [
                "unknown-account",
                "missing",
                "receiver-001",
                "10",
                "USD",
                "2026-10-15T00:00:00Z",
            ],
        ],
    )
    rejected = _upload(
        context["client"],
        _transaction_import_path(dataset_id),
        context["owner_headers"],
        invalid,
    )
    assert rejected.json()["status"] == "failed"
    assert rejected.json()["accepted_rows"] == 0
    assert rejected.json()["rejected_rows"] == 4
    assert {error["code"] for error in rejected.json()["row_errors"]} >= {
        "invalid_transaction_row",
        "unknown_account",
        "atomic_batch_rolled_back",
    }
    with context["factory"]() as db:
        transactions = db.scalars(
            select(Transaction).where(Transaction.dataset_id == dataset_id)
        ).all()
    assert len(transactions) == 2
    assert {tx.amount for tx in transactions} == {
        Decimal("1.123456"),
        Decimal("2.000001"),
    }


def test_csv_size_row_limit_and_cross_user_access(phase6_context, monkeypatch):
    context = phase6_context
    dataset_id = context["empty_dataset"].id
    path = _account_import_path(dataset_id)
    valid = _csv(["external_id"], [["acct-1"], ["acct-2"], ["acct-3"]])

    monkeypatch.setattr(settings, "CSV_MAX_UPLOAD_BYTES", 20)
    too_large = _upload(context["client"], path, context["owner_headers"], valid)
    assert too_large.json()["status"] == "failed"
    assert too_large.json()["row_errors"][0]["code"] == "file_too_large"

    monkeypatch.setattr(settings, "CSV_MAX_UPLOAD_BYTES", 10_485_760)
    monkeypatch.setattr(settings, "CSV_MAX_ROWS", 2)
    too_many_rows = _upload(context["client"], path, context["owner_headers"], valid)
    assert too_many_rows.json()["status"] == "failed"
    assert too_many_rows.json()["total_rows"] == 3
    assert too_many_rows.json()["rejected_rows"] == 3
    assert too_many_rows.json()["row_errors"][0]["code"] == "row_limit_exceeded"

    cross_user = _upload(
        context["client"],
        _account_import_path(dataset_id),
        context["other_headers"],
        valid,
    )
    assert cross_user.status_code == 404
    with context["factory"]() as db:
        assert (
            db.scalar(
                select(func.count(Account.id)).where(Account.dataset_id == dataset_id)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count(ImportJob.id)).where(
                    ImportJob.dataset_id == dataset_id
                )
            )
            == 2
        )


@pytest.mark.integration
def test_postgres_csv_persistence_and_rollback():
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required for this integration test.")
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        owner = User(
            email=f"phase6-import-{uuid4().hex}@example.com",
            password_hash=TEST_PASSWORD_HASH,
        )
        session.add(owner)
        session.flush()
        dataset = Dataset(owner_id=owner.id, name=f"csv-{uuid4().hex}")
        session.add(dataset)
        session.flush()

        accounts_csv = _csv(
            ["external_id", "account_type"],
            [["pg-sender", "business"], ["pg-receiver", "personal"]],
        )
        account_job, account_errors = import_accounts_csv(
            session,
            dataset_id=dataset.id,
            actor=owner,
            fileobj=BytesIO(accounts_csv.encode()),
            filename="postgres-accounts.csv",
        )
        assert account_job.accepted_rows == 2
        assert account_errors == []

        transactions_csv = _csv(
            [
                "external_transaction_id",
                "sender_external_id",
                "receiver_external_id",
                "amount",
                "currency",
                "occurred_at",
            ],
            [
                [
                    "pg-transfer",
                    "pg-sender",
                    "pg-receiver",
                    "3.141592",
                    "USD",
                    "2026-10-15T12:00:00Z",
                ]
            ],
        )
        transaction_job, transaction_errors = import_transactions_csv(
            session,
            dataset_id=dataset.id,
            actor=owner,
            fileobj=BytesIO(transactions_csv.encode()),
            filename="postgres-transactions.csv",
        )
        assert transaction_job.accepted_rows == 1
        assert transaction_errors == []
        assert session.scalar(
            select(Transaction.amount).where(
                Transaction.dataset_id == dataset.id,
                Transaction.external_transaction_id == "pg-transfer",
            )
        ) == Decimal("3.141592")

        invalid_atomic_batch = _csv(
            ["external_id"], [["valid-but-rolled-back"], ["", "extra"]]
        )
        failed_job, errors = import_accounts_csv(
            session,
            dataset_id=dataset.id,
            actor=owner,
            fileobj=BytesIO(invalid_atomic_batch.encode()),
            filename="invalid.csv",
        )
        assert failed_job.status == "failed"
        assert failed_job.accepted_rows == 0
        assert errors
        assert (
            session.scalar(
                select(func.count(Account.id)).where(Account.dataset_id == dataset.id)
            )
            == 2
        )
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()
