"""Cutoff-safe account and transaction feature extraction.

Ground-truth labels are intentionally absent from this module and its inputs.
All monetary aggregates use ``Decimal`` and remain currency-specific until the
preprocessor converts numeric values for a model.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any
from uuid import UUID

import networkx as nx

from app.graph.builder import TransactionGraph
from app.graph.metrics import account_metrics
from app.graph.models import decimal_value, normalize_utc
from app.ml.contracts import FeatureVector

FEATURE_SCHEMA_VERSION = "1.0"
ACTIVITY_WINDOWS: tuple[tuple[str, timedelta], ...] = (
    ("1h", timedelta(hours=1)),
    ("24h", timedelta(hours=24)),
    ("7d", timedelta(days=7)),
    ("30d", timedelta(days=30)),
)
SECONDS_PER_DAY = Decimal(86_400)


@dataclass(frozen=True, slots=True)
class FeatureBatch:
    dataset_id: UUID
    analysis_cutoff: datetime
    currencies: tuple[str, ...]
    account_features: tuple[FeatureVector, ...]
    transaction_features: tuple[FeatureVector, ...]


@dataclass(frozen=True, slots=True)
class _Transaction:
    id: UUID
    sender_id: UUID
    receiver_id: UUID
    amount: Decimal
    currency: str
    occurred_at: datetime


@dataclass(slots=True)
class _AccountHistory:
    last_at: datetime | None = None
    times: deque[datetime] | None = None
    incoming_times: deque[datetime] | None = None
    outgoing_times: deque[datetime] | None = None
    incoming_counterparties: set[UUID] | None = None
    outgoing_counterparties: set[UUID] | None = None
    incoming_amounts: dict[str, tuple[int, Decimal, Decimal]] | None = None
    outgoing_amounts: dict[str, tuple[int, Decimal, Decimal]] | None = None
    incoming_count: int = 0
    outgoing_count: int = 0
    total_count: int = 0

    def __post_init__(self) -> None:
        self.times = deque()
        self.incoming_times = deque()
        self.outgoing_times = deque()
        self.incoming_counterparties = set()
        self.outgoing_counterparties = set()
        self.incoming_amounts = {}
        self.outgoing_amounts = {}


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _variance(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal(0)
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    return sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(
        len(values)
    )


def _graph_transactions(
    graph: TransactionGraph, cutoff: datetime
) -> tuple[UUID, list[_Transaction]]:
    raw_dataset_id = graph.graph.get("dataset_id")
    if raw_dataset_id is None:
        raise ValueError("Graph must identify its dataset.")
    dataset_id = UUID(str(raw_dataset_id))
    transactions: list[_Transaction] = []
    seen: set[UUID] = set()
    for source, target, key, attrs in graph.edges(keys=True, data=True):
        transaction_id = UUID(str(attrs.get("transaction_id", key)))
        occurred_at = normalize_utc(attrs["occurred_at"], field_name="occurred_at")
        if occurred_at > cutoff:
            continue
        if transaction_id in seen:
            raise ValueError("Graph contains a duplicate transaction identifier.")
        seen.add(transaction_id)
        amount = decimal_value(attrs["amount"])
        currency = str(attrs["currency"]).strip().upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("Transaction currency must be a three-letter code.")
        transactions.append(
            _Transaction(
                id=transaction_id,
                sender_id=UUID(str(source)),
                receiver_id=UUID(str(target)),
                amount=amount,
                currency=currency,
                occurred_at=occurred_at,
            )
        )
    transactions.sort(key=lambda item: (item.occurred_at, str(item.id)))
    return dataset_id, transactions


def _historical_graph(
    graph: TransactionGraph,
    transactions: list[_Transaction],
    dataset_id: UUID,
) -> nx.MultiDiGraph:
    result = nx.MultiDiGraph(dataset_id=str(dataset_id), schema_version="1.0")
    active_accounts = {
        account_id
        for transaction in transactions
        for account_id in (transaction.sender_id, transaction.receiver_id)
    }
    for account_id in sorted(active_accounts, key=str):
        attrs = graph.nodes[account_id]
        result.add_node(account_id, **attrs)
    for transaction in transactions:
        result.add_edge(
            transaction.sender_id,
            transaction.receiver_id,
            key=transaction.id,
            transaction_id=transaction.id,
            dataset_id=dataset_id,
            amount=transaction.amount,
            currency=transaction.currency,
            occurred_at=transaction.occurred_at,
        )
    return result


def _account_feature_rows(
    historical_graph: nx.MultiDiGraph,
    transactions: list[_Transaction],
    currencies: tuple[str, ...],
    dataset_id: UUID,
    cutoff: datetime,
) -> tuple[FeatureVector, ...]:
    by_account: dict[UUID, list[_Transaction]] = defaultdict(list)
    for transaction in transactions:
        by_account[transaction.sender_id].append(transaction)
        if transaction.receiver_id != transaction.sender_id:
            by_account[transaction.receiver_id].append(transaction)

    active_accounts = sorted(by_account, key=str)
    node_divisor = Decimal(max(len(active_accounts) - 1, 1))
    rows: list[FeatureVector] = []
    for account_id in active_accounts:
        account_transactions = by_account[account_id]
        metrics = account_metrics(historical_graph, account_id)
        incoming = [
            transaction
            for transaction in account_transactions
            if transaction.receiver_id == account_id
        ]
        outgoing = [
            transaction
            for transaction in account_transactions
            if transaction.sender_id == account_id
        ]
        event_times = sorted(item.occurred_at for item in account_transactions)
        if len(event_times) > 1:
            gaps = [
                _decimal((right - left).total_seconds())
                for left, right in pairwise(event_times)
            ]
            average_gap: Decimal | None = sum(gaps, Decimal(0)) / Decimal(len(gaps))
        else:
            average_gap = None
        observation_seconds = max(
            _decimal((cutoff - event_times[0]).total_seconds()),
            SECONDS_PER_DAY,
        )
        observation_days = observation_seconds / SECONDS_PER_DAY
        features: dict[str, Any] = {
            "incoming_transaction_count": metrics.incoming_transaction_count,
            "outgoing_transaction_count": metrics.outgoing_transaction_count,
            "total_transaction_count": metrics.total_transaction_count,
            "unique_incoming_counterparties": metrics.unique_incoming_counterparty_count,
            "unique_outgoing_counterparties": metrics.unique_outgoing_counterparty_count,
            "total_unique_counterparties": metrics.total_unique_counterparty_count,
            "transaction_frequency_per_day": Decimal(metrics.total_transaction_count)
            / observation_days,
            "average_seconds_between_transactions": average_gap,
            "incoming_outgoing_count_ratio": Decimal(
                metrics.incoming_transaction_count + 1
            )
            / Decimal(metrics.outgoing_transaction_count + 1),
            "graph_in_degree": metrics.in_degree,
            "graph_out_degree": metrics.out_degree,
            "graph_in_degree_centrality": Decimal(metrics.in_degree) / node_divisor,
            "graph_out_degree_centrality": Decimal(metrics.out_degree) / node_divisor,
        }
        for label, window in ACTIVITY_WINDOWS:
            threshold = cutoff - window
            features[f"transaction_count_last_{label}"] = sum(
                item.occurred_at >= threshold for item in account_transactions
            )

        for currency in currencies:
            incoming_amounts = [
                item.amount for item in incoming if item.currency == currency
            ]
            outgoing_amounts = [
                item.amount for item in outgoing if item.currency == currency
            ]
            features[f"incoming_amount_{currency}"] = sum(
                incoming_amounts, Decimal(0)
            )
            features[f"outgoing_amount_{currency}"] = sum(
                outgoing_amounts, Decimal(0)
            )
            features[f"average_incoming_amount_{currency}"] = (
                sum(incoming_amounts, Decimal(0)) / Decimal(len(incoming_amounts))
                if incoming_amounts
                else Decimal(0)
            )
            features[f"average_outgoing_amount_{currency}"] = (
                sum(outgoing_amounts, Decimal(0)) / Decimal(len(outgoing_amounts))
                if outgoing_amounts
                else Decimal(0)
            )
            features[f"incoming_amount_variance_{currency}"] = _variance(
                incoming_amounts
            )
            features[f"outgoing_amount_variance_{currency}"] = _variance(
                outgoing_amounts
            )

        rows.append(
            FeatureVector(
                dataset_id=dataset_id,
                entity_type="ACCOUNT",
                entity_id=account_id,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                as_of=cutoff,
                features=features,
                group_id=account_id,
                related_account_ids=(account_id,),
            )
        )
    return tuple(rows)


def _amount_statistics(
    state: _AccountHistory, currency: str, *, direction: str
) -> tuple[int, Decimal, Decimal]:
    amounts = state.outgoing_amounts if direction == "outgoing" else state.incoming_amounts
    assert amounts is not None
    return amounts.get(currency, (0, Decimal(0), Decimal(0)))


def _prune_history(state: _AccountHistory, cutoff: datetime) -> None:
    threshold = cutoff - timedelta(days=30)
    for timestamps in (state.times, state.incoming_times, state.outgoing_times):
        assert timestamps is not None
        while timestamps and timestamps[0] < threshold:
            timestamps.popleft()


def _currency_amount_features(
    features: dict[str, Any],
    *,
    prefix: str,
    amount: Decimal,
    stats: tuple[int, Decimal, Decimal],
) -> None:
    count, total, squares = stats
    features[f"transaction_amount_{prefix}"] = amount
    if count == 0:
        features[f"amount_ratio_to_{prefix}_historical_mean"] = None
        features[f"amount_zscore_to_{prefix}_historical_mean"] = None
        return
    mean = total / Decimal(count)
    features[f"amount_ratio_to_{prefix}_historical_mean"] = (
        amount / mean if mean != 0 else None
    )
    if count < 2:
        features[f"amount_zscore_to_{prefix}_historical_mean"] = None
        return
    variance = max(squares / Decimal(count) - mean**2, Decimal(0))
    features[f"amount_zscore_to_{prefix}_historical_mean"] = (
        (amount - mean) / variance.sqrt() if variance > 0 else None
    )


def _transaction_feature_rows(
    transactions: list[_Transaction],
    currencies: tuple[str, ...],
    dataset_id: UUID,
) -> tuple[FeatureVector, ...]:
    states: dict[UUID, _AccountHistory] = {}
    output: list[FeatureVector] = []
    position = 0

    while position < len(transactions):
        occurred_at = transactions[position].occurred_at
        group_end = position + 1
        while (
            group_end < len(transactions)
            and transactions[group_end].occurred_at == occurred_at
        ):
            group_end += 1
        timestamp_group = transactions[position:group_end]
        pending_updates: list[tuple[_Transaction, UUID, UUID]] = []

        for transaction in timestamp_group:
            sender = states.setdefault(transaction.sender_id, _AccountHistory())
            receiver = states.setdefault(transaction.receiver_id, _AccountHistory())
            assert sender.times is not None and receiver.times is not None
            _prune_history(sender, occurred_at)
            if receiver is not sender:
                _prune_history(receiver, occurred_at)

            hour_angle = 2 * math.pi * occurred_at.hour / 24
            weekday_angle = 2 * math.pi * occurred_at.weekday() / 7
            features: dict[str, Any] = {
                "sender_historical_transaction_count": sender.total_count,
                "receiver_historical_transaction_count": receiver.total_count,
                "sender_transaction_count_last_30d": len(sender.times),
                "receiver_transaction_count_last_30d": len(receiver.times),
                "sender_outgoing_count_last_30d": len(sender.outgoing_times or ()),
                "receiver_incoming_count_last_30d": len(receiver.incoming_times or ()),
                "sender_unique_counterparty_count": len(
                    sender.outgoing_counterparties or ()
                ),
                "receiver_unique_counterparty_count": len(
                    receiver.incoming_counterparties or ()
                ),
                "sender_incoming_transaction_count": sender.incoming_count,
                "sender_outgoing_transaction_count": sender.outgoing_count,
                "receiver_incoming_transaction_count": receiver.incoming_count,
                "receiver_outgoing_transaction_count": receiver.outgoing_count,
                "seconds_since_sender_previous_transaction": (
                    _decimal((occurred_at - sender.last_at).total_seconds())
                    if sender.last_at is not None
                    else None
                ),
                "seconds_since_receiver_previous_transaction": (
                    _decimal((occurred_at - receiver.last_at).total_seconds())
                    if receiver.last_at is not None
                    else None
                ),
                "transaction_hour_sin": Decimal(str(math.sin(hour_angle))),
                "transaction_hour_cos": Decimal(str(math.cos(hour_angle))),
                "transaction_weekday_sin": Decimal(str(math.sin(weekday_angle))),
                "transaction_weekday_cos": Decimal(str(math.cos(weekday_angle))),
            }
            for currency in currencies:
                features[f"transaction_amount_{currency}"] = (
                    transaction.amount if transaction.currency == currency else Decimal(0)
                )
            _currency_amount_features(
                features,
                prefix="sender",
                amount=transaction.amount,
                stats=_amount_statistics(sender, transaction.currency, direction="outgoing"),
            )
            _currency_amount_features(
                features,
                prefix="receiver",
                amount=transaction.amount,
                stats=_amount_statistics(receiver, transaction.currency, direction="incoming"),
            )
            output.append(
                FeatureVector(
                    dataset_id=dataset_id,
                    entity_type="TRANSACTION",
                    entity_id=transaction.id,
                    feature_schema_version=FEATURE_SCHEMA_VERSION,
                    as_of=occurred_at,
                    features=features,
                    related_account_ids=(transaction.sender_id, transaction.receiver_id),
                    related_transaction_ids=(transaction.id,),
                )
            )
            pending_updates.append(
                (transaction, transaction.sender_id, transaction.receiver_id)
            )

        for transaction, sender_id, receiver_id in pending_updates:
            sender = states[sender_id]
            receiver = states[receiver_id]
            assert sender.times is not None and receiver.times is not None
            assert sender.outgoing_times is not None
            assert receiver.incoming_times is not None
            assert sender.outgoing_amounts is not None
            assert receiver.incoming_amounts is not None
            sender.times.append(occurred_at)
            sender.outgoing_times.append(occurred_at)
            sender.outgoing_count += 1
            sender.total_count += 1
            if receiver_id != sender_id:
                receiver.times.append(occurred_at)
                receiver.incoming_times.append(occurred_at)
                receiver.incoming_count += 1
                receiver.total_count += 1
            else:
                sender.incoming_times.append(occurred_at)
                sender.incoming_count += 1
            if sender_id != receiver_id:
                assert sender.outgoing_counterparties is not None
                assert receiver.incoming_counterparties is not None
                sender.outgoing_counterparties.add(receiver_id)
                receiver.incoming_counterparties.add(sender_id)
            sender.outgoing_amounts[transaction.currency] = _add_amount(
                sender.outgoing_amounts.get(
                    transaction.currency, (0, Decimal(0), Decimal(0))
                ),
                transaction.amount,
            )
            receiver.incoming_amounts[transaction.currency] = _add_amount(
                receiver.incoming_amounts.get(
                    transaction.currency, (0, Decimal(0), Decimal(0))
                ),
                transaction.amount,
            )
            sender.last_at = receiver.last_at = occurred_at

        position = group_end

    return tuple(output)


def _add_amount(
    current: tuple[int, Decimal, Decimal], amount: Decimal
) -> tuple[int, Decimal, Decimal]:
    count, total, squares = current
    return count + 1, total + amount, squares + amount**2


def extract_features(
    graph: TransactionGraph, *, analysis_cutoff: datetime
) -> FeatureBatch:
    """Extract bounded, cutoff-aware features from one Phase 7 graph.

    Transactions after ``analysis_cutoff`` are excluded. Transaction-level
    histories include only strictly earlier timestamps; rows at the same time
    cannot leak information into one another. Accounts with no transactions by
    the cutoff are omitted from model samples.
    """

    cutoff = normalize_utc(analysis_cutoff, field_name="analysis_cutoff")
    dataset_id, transactions = _graph_transactions(graph, cutoff)
    currencies = tuple(sorted({item.currency for item in transactions}))
    historical_graph = _historical_graph(graph, transactions, dataset_id)
    account_features = _account_feature_rows(
        historical_graph, transactions, currencies, dataset_id, cutoff
    )
    transaction_features = _transaction_feature_rows(
        transactions, currencies, dataset_id
    )
    # Use undirected transaction components to keep all related accounts
    # together during held-out transaction evaluation.
    component_id: dict[UUID, UUID] = {}
    for component in nx.connected_components(historical_graph.to_undirected()):
        stable_id = min(component, key=str)
        for account_id in component:
            component_id[account_id] = stable_id
    transaction_features = tuple(
        vector.model_copy(
            update={
                "group_id": component_id[vector.related_account_ids[0]],
            }
        )
        for vector in transaction_features
    )
    return FeatureBatch(
        dataset_id=dataset_id,
        analysis_cutoff=cutoff,
        currencies=currencies,
        account_features=account_features,
        transaction_features=transaction_features,
    )
