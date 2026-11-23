"""Cutoff-safe, currency-separated ML feature extraction tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.graph.builder import build_transaction_graph
from app.graph.models import AccountRecord, TransactionRecord
from app.ml.features import extract_features

BASE_TIME = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _graph(*, transactions: tuple[TransactionRecord, ...]):
    dataset_id = transactions[0].dataset_id
    account_ids = tuple(
        sorted(
            {
                account_id
                for item in transactions
                for account_id in (item.sender_account_id, item.receiver_account_id)
            },
            key=str,
        )
    )
    accounts = tuple(AccountRecord(id=item, dataset_id=dataset_id) for item in account_ids)
    return (
        dataset_id,
        account_ids,
        build_transaction_graph(dataset_id, accounts, transactions),
    )


def test_account_and_transaction_features_are_cutoff_safe_and_currency_specific():
    dataset_id = UUID("10000000-0000-0000-0000-000000000001")
    a, b, c, _ = tuple(
        UUID(f"20000000-0000-0000-0000-{index:012d}") for index in range(1, 5)
    )
    t1, t2, t3, future = (uuid4() for _ in range(4))
    transactions = (
        TransactionRecord(t1, dataset_id, a, b, Decimal("0.10"), "USD", BASE_TIME),
        TransactionRecord(
            t2,
            dataset_id,
            a,
            c,
            Decimal("0.20"),
            "EUR",
            BASE_TIME + timedelta(seconds=60),
        ),
        TransactionRecord(
            t3,
            dataset_id,
            b,
            a,
            Decimal("0.30"),
            "USD",
            BASE_TIME + timedelta(seconds=120),
        ),
        TransactionRecord(
            future,
            dataset_id,
            a,
            b,
            Decimal("99.99"),
            "USD",
            BASE_TIME + timedelta(seconds=180),
        ),
    )
    _, _, graph = _graph(transactions=transactions)
    batch = extract_features(
        graph, analysis_cutoff=BASE_TIME + timedelta(seconds=120)
    )

    account = next(row for row in batch.account_features if row.entity_id == a)
    assert account.features["incoming_transaction_count"] == 1
    assert account.features["outgoing_transaction_count"] == 2
    assert account.features["total_unique_counterparties"] == 2
    assert account.features["incoming_amount_USD"] == Decimal("0.30")
    assert account.features["outgoing_amount_USD"] == Decimal("0.10")
    assert account.features["outgoing_amount_EUR"] == Decimal("0.20")
    assert account.features["incoming_amount_EUR"] == Decimal(0)
    assert account.features["outgoing_amount_variance_USD"] == Decimal(0)
    assert account.features["transaction_count_last_1h"] == 3
    assert batch.currencies == ("EUR", "USD")
    assert future not in {row.entity_id for row in batch.transaction_features}

    latest_transaction = next(row for row in batch.transaction_features if row.entity_id == t3)
    assert latest_transaction.as_of == BASE_TIME + timedelta(seconds=120)
    assert latest_transaction.features["sender_historical_transaction_count"] == 1
    assert latest_transaction.features["receiver_historical_transaction_count"] == 2
    assert latest_transaction.features["seconds_since_sender_previous_transaction"] == Decimal(
        120
    )
    assert latest_transaction.features[
        "seconds_since_receiver_previous_transaction"
    ] == Decimal(60)
    assert latest_transaction.features["transaction_amount_USD"] == Decimal("0.30")
    assert latest_transaction.features["transaction_amount_EUR"] == Decimal(0)
    assert latest_transaction.features["amount_ratio_to_sender_historical_mean"] is None
    assert latest_transaction.related_transaction_ids == (t3,)
    assert latest_transaction.group_id == a


def test_same_timestamp_transactions_do_not_leak_into_each_others_history():
    dataset_id = UUID("10000000-0000-0000-0000-000000000002")
    a, b, c, _ = tuple(
        UUID(f"30000000-0000-0000-0000-{index:012d}") for index in range(1, 5)
    )
    first, second = uuid4(), uuid4()
    txs = (
        TransactionRecord(first, dataset_id, a, b, Decimal("5.00"), "USD", BASE_TIME),
        TransactionRecord(second, dataset_id, a, c, Decimal("7.00"), "USD", BASE_TIME),
    )
    _, _, graph = _graph(transactions=txs)
    batch = extract_features(graph, analysis_cutoff=BASE_TIME)

    for vector in batch.transaction_features:
        assert vector.features["sender_historical_transaction_count"] == 0
        assert vector.features["receiver_historical_transaction_count"] == 0
        assert vector.features["seconds_since_sender_previous_transaction"] is None

    sender = next(row for row in batch.account_features if row.entity_id == a)
    assert sender.features["average_seconds_between_transactions"] == Decimal(0)
