"""Account-level graph metrics with explicit parallel-edge semantics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.graph.builder import TransactionGraph
from app.graph.models import (
    AccountMetrics,
    TransactionActivity,
    normalize_utc,
)


class AccountNotInGraphError(KeyError):
    """Raised when an account metric is requested for a missing graph node."""


def _require_account(graph: TransactionGraph, account_id: UUID) -> None:
    if account_id not in graph:
        raise AccountNotInGraphError(str(account_id))


def _amount_totals(edges) -> dict[str, Decimal]:
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    for _, _, _, attributes in edges:
        totals[attributes["currency"]] += attributes["amount"]
    return dict(sorted(totals.items()))


def account_metrics(graph: TransactionGraph, account_id: UUID) -> AccountMetrics:
    """Return edge counts, unique counterparties, and currency-separated totals.

    In/out degree and transaction counts include every parallel edge. Total
    degree is NetworkX in-degree plus out-degree (a self-loop contributes two).
    Total transaction count counts each distinct transaction once. Counterparty
    counts are unique adjacent accounts and exclude the subject account itself.
    """

    _require_account(graph, account_id)
    incoming = list(graph.in_edges(account_id, keys=True, data=True))
    outgoing = list(graph.out_edges(account_id, keys=True, data=True))
    incoming_counterparties = {
        source for source, _, _, _ in incoming if source != account_id
    }
    outgoing_counterparties = {
        target for _, target, _, _ in outgoing if target != account_id
    }
    transaction_keys = {key for _, _, key, _ in incoming}
    transaction_keys.update(key for _, _, key, _ in outgoing)
    in_degree = int(graph.in_degree(account_id))
    out_degree = int(graph.out_degree(account_id))
    return AccountMetrics(
        account_id=account_id,
        in_degree=in_degree,
        out_degree=out_degree,
        total_degree=in_degree + out_degree,
        incoming_transaction_count=len(incoming),
        outgoing_transaction_count=len(outgoing),
        total_transaction_count=len(transaction_keys),
        unique_incoming_counterparty_count=len(incoming_counterparties),
        unique_outgoing_counterparty_count=len(outgoing_counterparties),
        total_unique_counterparty_count=len(
            incoming_counterparties | outgoing_counterparties
        ),
        incoming_amount_by_currency=_amount_totals(incoming),
        outgoing_amount_by_currency=_amount_totals(outgoing),
    )


def transaction_activity(
    graph: TransactionGraph,
    account_id: UUID,
    *,
    start_at: datetime,
    end_at: datetime,
) -> TransactionActivity:
    """Count a node's transaction activity in the half-open UTC window [start,end)."""

    _require_account(graph, account_id)
    start = normalize_utc(start_at, field_name="start_at")
    end = normalize_utc(end_at, field_name="end_at")
    if start >= end:
        raise ValueError("start_at must be earlier than end_at.")

    incoming = 0
    outgoing = 0
    incoming_keys: set[UUID] = set()
    outgoing_keys: set[UUID] = set()
    for _, _, key, attributes in graph.in_edges(account_id, keys=True, data=True):
        occurred_at = normalize_utc(attributes["occurred_at"], field_name="occurred_at")
        if start <= occurred_at < end:
            incoming += 1
            incoming_keys.add(key)
    for _, _, key, attributes in graph.out_edges(account_id, keys=True, data=True):
        occurred_at = normalize_utc(attributes["occurred_at"], field_name="occurred_at")
        if start <= occurred_at < end:
            outgoing += 1
            outgoing_keys.add(key)
    return TransactionActivity(
        account_id=account_id,
        start_at=start,
        end_at=end,
        incoming_transaction_count=incoming,
        outgoing_transaction_count=outgoing,
        total_transaction_count=len(incoming_keys | outgoing_keys),
    )
