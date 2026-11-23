"""Pure construction of directed, transaction-preserving graph instances."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

import networkx as nx

from app.graph.models import (
    DEFAULT_GRAPH_LIMITS,
    AccountRecord,
    GraphFilters,
    GraphLimitExceeded,
    GraphLimits,
    GraphRecordError,
    TransactionRecord,
    decimal_value,
    normalize_utc,
)

TransactionGraph = nx.MultiDiGraph


def _within_time_window(
    occurred_at: datetime,
    *,
    start_at: datetime | None,
    end_at: datetime | None,
) -> bool:
    return not (
        (start_at is not None and occurred_at < start_at)
        or (end_at is not None and occurred_at >= end_at)
    )


def build_transaction_graph(
    dataset_id: UUID,
    accounts: Iterable[AccountRecord],
    transactions: Iterable[TransactionRecord],
    *,
    filters: GraphFilters | None = None,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> TransactionGraph:
    """Build an isolated MultiDiGraph without changing the supplied records.

    The graph key is each account UUID. Its edge key is the transaction UUID,
    so parallel transfers remain separate. Time filtering uses ``[start_at,
    end_at)``; currency and amount bounds are inclusive where specified.
    Transactions outside the selected dataset or without both selected accounts
    are ignored instead of creating phantom nodes.
    """

    filters = filters or GraphFilters()
    if (
        filters.account_ids is not None
        and len(filters.account_ids) > limits.max_accounts
    ):
        raise GraphLimitExceeded(
            f"Account filters cannot exceed {limits.max_accounts} IDs."
        )

    graph = nx.MultiDiGraph(
        dataset_id=str(dataset_id),
        schema_version="1.0",
        filters=filters.metadata(),
    )
    selected_account_ids: set[UUID] = set()
    for record in accounts:
        if record.dataset_id != dataset_id:
            continue
        if filters.account_ids is not None and record.id not in filters.account_ids:
            continue
        if record.id in selected_account_ids:
            raise GraphRecordError(f"Duplicate account ID {record.id} in graph input.")
        if len(selected_account_ids) >= limits.max_accounts:
            raise GraphLimitExceeded(
                f"Dataset graph exceeds the {limits.max_accounts}-account limit."
            )
        selected_account_ids.add(record.id)
        graph.add_node(
            record.id,
            account_id=record.id,
            dataset_id=record.dataset_id,
            account_type=record.account_type,
            institution_code=record.institution_code,
            country_code=record.country_code,
        )

    transaction_ids: set[UUID] = set()
    for record in transactions:
        if record.dataset_id != dataset_id:
            continue
        if (
            record.sender_account_id not in selected_account_ids
            or record.receiver_account_id not in selected_account_ids
        ):
            continue

        amount = decimal_value(record.amount)
        occurred_at = normalize_utc(record.occurred_at, field_name="occurred_at")
        currency = record.currency.strip().upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise GraphRecordError(f"Transaction {record.id} has an invalid currency.")
        if amount <= 0:
            raise GraphRecordError(
                f"Transaction {record.id} has a non-positive amount."
            )
        if not _within_time_window(
            occurred_at, start_at=filters.start_at, end_at=filters.end_at
        ):
            continue
        if filters.currency is not None and currency != filters.currency:
            continue
        if filters.minimum_amount is not None and amount < filters.minimum_amount:
            continue
        if filters.maximum_amount is not None and amount > filters.maximum_amount:
            continue

        if record.id in transaction_ids:
            raise GraphRecordError(
                f"Duplicate transaction ID {record.id} in graph input."
            )
        if len(transaction_ids) >= limits.max_transactions:
            raise GraphLimitExceeded(
                f"Dataset graph exceeds the {limits.max_transactions}-transaction limit."
            )
        transaction_ids.add(record.id)
        graph.add_edge(
            record.sender_account_id,
            record.receiver_account_id,
            key=record.id,
            transaction_id=record.id,
            dataset_id=record.dataset_id,
            amount=amount,
            currency=currency,
            occurred_at=occurred_at,
            transaction_type=record.transaction_type,
            channel=record.channel,
            status=record.status,
        )

    graph.graph["node_count"] = graph.number_of_nodes()
    graph.graph["edge_count"] = graph.number_of_edges()
    return graph
