from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
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
from app.models import Account, AuditLog, Dataset, Transaction, User
from app.security.tokens import create_access_token
from app.services.accounts import create_account
from app.services.dataset_access import ResourceConflict
from app.services.transactions import create_transaction

TEST_JWT_SECRET = "phase-five-test-secret-value-with-at-least-32-bytes"
TEST_PASSWORD_HASH = "test-only-password-hash"


@pytest.fixture
def resource_context(monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
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

    owner = User(email="owner@example.com", password_hash=TEST_PASSWORD_HASH)
    other_user = User(email="other@example.com", password_hash=TEST_PASSWORD_HASH)
    with factory() as db:
        db.add_all([owner, other_user])
        db.flush()
        dataset = Dataset(owner_id=owner.id, name="Owner dataset")
        other_dataset = Dataset(owner_id=other_user.id, name="Other dataset")
        db.add_all([dataset, other_dataset])
        db.flush()
        sender = Account(
            dataset_id=dataset.id,
            external_id="sender-001",
            account_type="business",
            country_code="US",
        )
        receiver = Account(
            dataset_id=dataset.id,
            external_id="receiver-001",
            account_type="personal",
            country_code="GB",
        )
        other_account = Account(
            dataset_id=other_dataset.id,
            external_id="other-001",
            account_type="business",
        )
        db.add_all([sender, receiver, other_account])
        db.commit()
        for entity in (
            owner,
            other_user,
            dataset,
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
            "dataset": dataset,
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


def _account_path(dataset_id: UUID) -> str:
    return f"/api/v1/datasets/{dataset_id}/accounts"


def _transaction_path(dataset_id: UUID) -> str:
    return f"/api/v1/datasets/{dataset_id}/transactions"


def _assert_utc(timestamp: str) -> None:
    normalized = datetime.fromisoformat(timestamp)
    assert normalized.utcoffset() == UTC.utcoffset(normalized)


def _transaction_payload(context: dict, **overrides) -> dict:
    payload = {
        "sender_account_id": str(context["sender"].id),
        "receiver_account_id": str(context["receiver"].id),
        "external_transaction_id": f"external-{uuid4().hex}",
        "amount": "125.450000",
        "currency": "usd",
        "transaction_type": "transfer",
        "channel": "online",
        "status": "settled",
        "occurred_at": "2026-10-15T12:30:00+05:30",
        "metadata": {"source": "test"},
    }
    payload.update(overrides)
    return payload


def test_account_create_retrieve_list_update_and_summary(resource_context):
    context = resource_context
    client = context["client"]
    base_path = _account_path(context["dataset"].id)
    created = client.post(
        base_path,
        headers=context["owner_headers"],
        json={
            "external_id": "  new-account  ",
            "account_type": "business",
            "country_code": "ca",
            "metadata": {"origin": "manual"},
        },
    )
    assert created.status_code == 201
    account = created.json()
    assert account["external_id"] == "new-account"
    assert account["country_code"] == "CA"
    assert account["transaction_count"] == 0
    assert account["metadata"] == {"origin": "manual"}

    retrieved = client.get(
        f"{base_path}/{account['id']}", headers=context["owner_headers"]
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == account["id"]

    listed = client.get(
        base_path,
        headers=context["owner_headers"],
        params={
            "account_type": "business",
            "country_code": "ca",
            "page": 1,
            "page_size": 1,
        },
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["total_pages"] == 1
    assert listed.json()["items"][0]["id"] == account["id"]

    first_account_page = client.get(
        base_path,
        headers=context["owner_headers"],
        params={"page": 1, "page_size": 1},
    )
    second_account_page = client.get(
        base_path,
        headers=context["owner_headers"],
        params={"page": 2, "page_size": 1},
    )
    assert first_account_page.json()["total"] == 3
    assert first_account_page.json()["total_pages"] == 3
    assert (
        first_account_page.json()["items"][0]["id"]
        != second_account_page.json()["items"][0]["id"]
    )

    updated = client.patch(
        f"{base_path}/{account['id']}",
        headers=context["owner_headers"],
        json={"institution_code": "BANK-CA", "metadata": {"reviewed": True}},
    )
    assert updated.status_code == 200
    assert updated.json()["institution_code"] == "BANK-CA"
    assert updated.json()["metadata"] == {"reviewed": True}

    tx_path = _transaction_path(context["dataset"].id)
    tx_response = client.post(
        tx_path,
        headers=context["owner_headers"],
        json=_transaction_payload(
            context,
            sender_account_id=account["id"],
        ),
    )
    assert tx_response.status_code == 201
    assert (
        client.get(
            f"{base_path}/{account['id']}", headers=context["owner_headers"]
        ).json()["transaction_count"]
        == 1
    )

    with context["factory"]() as db:
        events = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == UUID(account["id"]),
                AuditLog.event_type.in_(["account.created", "account.updated"]),
            )
        ).all()
    assert {event.event_type for event in events} == {
        "account.created",
        "account.updated",
    }
    assert all(event.request_id for event in events)
    assert all("new-account" not in str(event.details) for event in events)


def test_account_access_is_authenticated_and_scoped_to_dataset_owner(resource_context):
    context = resource_context
    client = context["client"]
    owner_path = _account_path(context["dataset"].id)
    other_path = _account_path(context["other_dataset"].id)

    missing_auth = client.get(owner_path)
    assert missing_auth.status_code == 401
    assert missing_auth.json()["error"]["code"] == "unauthorized"

    hidden_dataset = client.get(other_path, headers=context["owner_headers"])
    rejected_create = client.post(
        other_path,
        headers=context["owner_headers"],
        json={"external_id": "must-not-exist"},
    )
    assert hidden_dataset.status_code == rejected_create.status_code == 404
    assert hidden_dataset.json()["error"]["code"] == "not_found"

    wrong_dataset_account = client.get(
        f"{owner_path}/{context['other_account'].id}",
        headers=context["owner_headers"],
    )
    assert wrong_dataset_account.status_code == 404

    invalid_id = client.get(
        f"{owner_path}/not-a-uuid", headers=context["owner_headers"]
    )
    assert invalid_id.status_code == 422
    assert (
        invalid_id.json()["error"]["request_id"] == invalid_id.headers["x-request-id"]
    )

    protected_fields = client.patch(
        f"{owner_path}/{context['sender'].id}",
        headers=context["owner_headers"],
        json={"dataset_id": str(context["other_dataset"].id)},
    )
    assert protected_fields.status_code == 422


def test_duplicate_account_conflict_rolls_back_and_hides_database_error(
    resource_context,
):
    context = resource_context
    response = context["client"].post(
        _account_path(context["dataset"].id),
        headers=context["owner_headers"],
        json={"external_id": "sender-001"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "IntegrityError" not in response.text
    with context["factory"]() as db:
        count = db.scalar(
            select(func.count(Account.id)).where(
                Account.dataset_id == context["dataset"].id
            )
        )
    assert count == 2


def test_transaction_create_retrieve_paging_filtering_sorting_and_summary(
    resource_context,
):
    context = resource_context
    client = context["client"]
    base_path = _transaction_path(context["dataset"].id)

    first = client.post(
        base_path,
        headers=context["owner_headers"],
        json=_transaction_payload(
            context, amount="15.250000", occurred_at="2026-10-15T00:00:00Z"
        ),
    )
    second = client.post(
        base_path,
        headers=context["owner_headers"],
        json=_transaction_payload(
            context, amount="125.450000", occurred_at="2026-10-16T00:00:00Z"
        ),
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["currency"] == "USD"
    assert first.json()["amount"] == "15.250000"
    _assert_utc(first.json()["occurred_at"])
    assert first.json()["sender_account_id"] == str(context["sender"].id)
    assert first.json()["id"] != second.json()["id"]

    read_response = client.get(
        f"{base_path}/{first.json()['id']}", headers=context["owner_headers"]
    )
    assert read_response.status_code == 200
    assert (
        read_response.json()["external_transaction_id"]
        == first.json()["external_transaction_id"]
    )

    page_one = client.get(
        base_path,
        headers=context["owner_headers"],
        params={
            "account_id": str(context["sender"].id),
            "page": 1,
            "page_size": 1,
            "sort_by": "amount",
            "sort_order": "asc",
        },
    )
    page_two = client.get(
        base_path,
        headers=context["owner_headers"],
        params={
            "account_id": str(context["sender"].id),
            "page": 2,
            "page_size": 1,
            "sort_by": "amount",
            "sort_order": "asc",
        },
    )
    assert page_one.status_code == page_two.status_code == 200
    assert page_one.json()["total"] == 2
    assert page_one.json()["total_pages"] == 2
    assert page_one.json()["items"][0]["id"] == first.json()["id"]
    assert page_two.json()["items"][0]["id"] == second.json()["id"]

    filtered = client.get(
        base_path,
        headers=context["owner_headers"],
        params={
            "sender_account_id": str(context["sender"].id),
            "receiver_account_id": str(context["receiver"].id),
            "min_amount": "100",
            "max_amount": "150",
            "currency": "usd",
            "start_at": "2026-10-15T12:00:00+00:00",
            "end_at": "2026-10-17T00:00:00+00:00",
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == second.json()["id"]

    by_receiver = client.get(
        base_path,
        headers=context["owner_headers"],
        params={"receiver_account_id": str(context["receiver"].id)},
    )
    assert by_receiver.json()["total"] == 2

    with context["factory"]() as db:
        persisted = db.scalars(
            select(Transaction).where(Transaction.dataset_id == context["dataset"].id)
        ).all()
    assert len(persisted) == 2
    assert all(row.sender_account_id == context["sender"].id for row in persisted)

    account_summary = client.get(
        f"/api/v1/datasets/{context['dataset'].id}/accounts/{context['sender'].id}",
        headers=context["owner_headers"],
    )
    assert account_summary.status_code == 200
    assert account_summary.json()["transaction_count"] == 2


def test_transactions_reject_invalid_amount_time_currency_and_account_scope(
    resource_context,
):
    context = resource_context
    client = context["client"]
    base_path = _transaction_path(context["dataset"].id)
    invalid_payloads = [
        _transaction_payload(context, amount="0"),
        _transaction_payload(context, amount="1.1234567"),
        _transaction_payload(context, occurred_at="2026-10-15T12:30:00"),
        _transaction_payload(context, currency="US1"),
        _transaction_payload(
            context,
            receiver_account_id=str(context["sender"].id),
        ),
    ]
    for payload in invalid_payloads:
        response = client.post(
            base_path, headers=context["owner_headers"], json=payload
        )
        assert response.status_code == 422
        assert payload["external_transaction_id"] not in response.text

    cross_dataset = client.post(
        base_path,
        headers=context["owner_headers"],
        json=_transaction_payload(
            context,
            receiver_account_id=str(context["other_account"].id),
        ),
    )
    assert cross_dataset.status_code == 422
    assert cross_dataset.json()["error"]["code"] == "validation_error"

    invalid_range = client.get(
        base_path,
        headers=context["owner_headers"],
        params={"min_amount": "20", "max_amount": "10"},
    )
    assert invalid_range.status_code == 422
    naive_time_filter = client.get(
        base_path,
        headers=context["owner_headers"],
        params={"start_at": "2026-10-15T12:00:00"},
    )
    assert naive_time_filter.status_code == 422
    invalid_sort = client.get(
        base_path,
        headers=context["owner_headers"],
        params={"sort_by": "external_transaction_id"},
    )
    assert invalid_sort.status_code == 422
    invalid_id = client.get(f"{base_path}/not-a-uuid", headers=context["owner_headers"])
    assert invalid_id.status_code == 422

    with context["factory"]() as db:
        assert db.scalar(select(func.count(Transaction.id))) == 0
        assert db.scalar(select(func.count(AuditLog.id))) == 0


def test_transaction_update_is_limited_and_audited(resource_context):
    context = resource_context
    client = context["client"]
    base_path = _transaction_path(context["dataset"].id)
    created = client.post(
        base_path,
        headers=context["owner_headers"],
        json=_transaction_payload(context),
    )
    transaction_id = created.json()["id"]

    updated = client.patch(
        f"{base_path}/{transaction_id}",
        headers=context["owner_headers"],
        json={
            "amount": "99.990000",
            "status": "reviewed",
            "occurred_at": "2026-10-17T12:00:00+03:00",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["amount"] == "99.990000"
    assert updated.json()["status"] == "reviewed"
    _assert_utc(updated.json()["occurred_at"])

    protected_fields = client.patch(
        f"{base_path}/{transaction_id}",
        headers=context["owner_headers"],
        json={"sender_account_id": str(context["receiver"].id)},
    )
    assert protected_fields.status_code == 422

    with context["factory"]() as db:
        events = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == UUID(transaction_id),
                AuditLog.entity_type == "transaction",
            )
        ).all()
        transaction = db.get(Transaction, UUID(transaction_id))
    assert {event.event_type for event in events} == {
        "transaction.created",
        "transaction.updated",
    }
    assert all("amount" not in event.details.values() for event in events)
    assert transaction.amount == Decimal("99.990000")


def test_duplicate_external_transaction_id_conflict_rolls_back(resource_context):
    context = resource_context
    client = context["client"]
    base_path = _transaction_path(context["dataset"].id)
    payload = _transaction_payload(context, external_transaction_id="same-external-id")
    first = client.post(base_path, headers=context["owner_headers"], json=payload)
    second = client.post(base_path, headers=context["owner_headers"], json=payload)
    assert first.status_code == 201
    assert second.status_code == 409
    assert "IntegrityError" not in second.text
    with context["factory"]() as db:
        assert db.scalar(select(func.count(Transaction.id))) == 1
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.event_type == "transaction.created"
                )
            )
            == 1
        )


def test_dataset_owned_by_another_user_cannot_read_transaction(resource_context):
    context = resource_context
    client = context["client"]
    base_path = _transaction_path(context["dataset"].id)
    created = client.post(
        base_path,
        headers=context["owner_headers"],
        json=_transaction_payload(context),
    )
    assert created.status_code == 201
    hidden = client.get(
        f"{base_path}/{created.json()['id']}",
        headers=context["other_headers"],
    )
    assert hidden.status_code == 404
    other_dataset_list = client.get(
        _transaction_path(context["dataset"].id),
        headers=context["other_headers"],
    )
    assert other_dataset_list.status_code == 404


@pytest.mark.integration
def test_postgres_resource_persistence_and_failed_write_rollback():
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required for this integration test.")
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        owner = User(
            email=f"resource-integration-{uuid4().hex}@example.com",
            password_hash=TEST_PASSWORD_HASH,
        )
        session.add(owner)
        session.flush()
        dataset = Dataset(owner_id=owner.id, name=f"integration-{uuid4().hex}")
        session.add(dataset)
        session.flush()
        sender = create_account(
            session,
            dataset_id=dataset.id,
            actor=owner,
            fields={"external_id": f"sender-{uuid4().hex}"},
        )[0]
        receiver = create_account(
            session,
            dataset_id=dataset.id,
            actor=owner,
            fields={"external_id": f"receiver-{uuid4().hex}"},
        )[0]
        assert (
            session.scalar(select(Account.id).where(Account.id == sender.id))
            is not None
        )
        assert (
            session.scalar(select(Account.id).where(Account.id == receiver.id))
            is not None
        )
        with pytest.raises(ResourceConflict):
            create_account(
                session,
                dataset_id=dataset.id,
                actor=owner,
                fields={"external_id": sender.external_id},
            )
        assert (
            session.scalar(
                select(func.count(Account.id)).where(Account.dataset_id == dataset.id)
            )
            == 2
        )
        transaction = create_transaction(
            session,
            dataset_id=dataset.id,
            actor=owner,
            fields={
                "sender_account_id": sender.id,
                "receiver_account_id": receiver.id,
                "external_transaction_id": "persisted-external-id",
                "amount": Decimal("5.123456"),
                "currency": "USD",
                "occurred_at": datetime.now(UTC),
                "metadata": {},
            },
        )
        assert (
            session.scalar(
                select(Transaction.id).where(Transaction.id == transaction.id)
            )
            == transaction.id
        )
        with pytest.raises(ResourceConflict):
            create_transaction(
                session,
                dataset_id=dataset.id,
                actor=owner,
                fields={
                    "sender_account_id": sender.id,
                    "receiver_account_id": receiver.id,
                    "external_transaction_id": "persisted-external-id",
                    "amount": Decimal("8.000000"),
                    "currency": "USD",
                    "occurred_at": datetime.now(UTC),
                    "metadata": {},
                },
            )
        assert (
            session.scalar(
                select(func.count(Transaction.id)).where(
                    Transaction.dataset_id == dataset.id
                )
            )
            == 1
        )
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()
