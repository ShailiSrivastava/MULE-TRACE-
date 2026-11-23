"""Deterministic, bounded transaction-level directed path discovery."""

from __future__ import annotations

from uuid import UUID

from app.graph.builder import TransactionGraph
from app.graph.models import (
    DEFAULT_GRAPH_LIMITS,
    GraphLimitExceeded,
    GraphLimits,
    GraphPath,
    PathSearchResult,
    PathTransaction,
    decimal_value,
    normalize_utc,
)


def find_bounded_paths(
    graph: TransactionGraph,
    source: UUID,
    target: UUID,
    *,
    max_hops: int = 4,
    max_paths: int = 20,
    max_expansions: int | None = None,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> PathSearchResult:
    """Find simple directed account paths while retaining each transaction edge.

    Parallel transactions produce distinct path results. Repeated accounts are
    not traversed, so cycles and self-loops cannot cause infinite traversal.
    Results are deterministic by target account UUID and transaction UUID.
    Search is hard-bounded by hop, result, and expanded-edge limits; ``truncated``
    indicates that another path or the expansion bound stopped enumeration.
    """

    if max_hops < 1 or max_hops > limits.max_path_hops:
        raise GraphLimitExceeded(
            f"max_hops must be between 1 and {limits.max_path_hops}."
        )
    if max_paths < 1 or max_paths > limits.max_paths:
        raise GraphLimitExceeded(f"max_paths must be between 1 and {limits.max_paths}.")
    if max_expansions is None:
        max_expansions = limits.max_path_expansions
    if max_expansions < 1 or max_expansions > limits.max_path_expansions:
        raise GraphLimitExceeded(
            f"max_expansions must be between 1 and {limits.max_path_expansions}."
        )

    source_found = source in graph
    target_found = target in graph
    if not source_found or not target_found or source == target:
        return PathSearchResult(
            source_found=source_found,
            target_found=target_found,
            paths=(),
            truncated=False,
            expanded_edges=0,
        )

    paths: list[GraphPath] = []
    expanded_edges = 0
    truncated = False
    stop_search = False

    def visit(
        current: UUID,
        accounts: tuple[UUID, ...],
        transactions: tuple[PathTransaction, ...],
        visited: frozenset[UUID],
    ) -> None:
        nonlocal expanded_edges, truncated, stop_search
        if stop_search or len(transactions) >= max_hops:
            return

        outgoing = sorted(
            graph.out_edges(current, keys=True, data=True),
            key=lambda edge: (str(edge[1]), str(edge[2])),
        )
        for _, next_account, transaction_id, attributes in outgoing:
            if expanded_edges >= max_expansions:
                truncated = True
                stop_search = True
                return
            expanded_edges += 1
            if next_account in visited:
                continue

            edge_transaction_id = attributes.get("transaction_id", transaction_id)
            edge = PathTransaction(
                transaction_id=edge_transaction_id,
                source=current,
                target=next_account,
                amount=decimal_value(attributes["amount"]),
                currency=attributes["currency"],
                occurred_at=normalize_utc(
                    attributes["occurred_at"], field_name="occurred_at"
                ),
            )
            next_accounts = (*accounts, next_account)
            next_transactions = (*transactions, edge)
            if next_account == target:
                if len(paths) == max_paths:
                    truncated = True
                    stop_search = True
                    return
                paths.append(
                    GraphPath(accounts=next_accounts, transactions=next_transactions)
                )
            else:
                visit(
                    next_account,
                    next_accounts,
                    next_transactions,
                    visited | {next_account},
                )
                if stop_search:
                    return

    visit(source, (source,), (), frozenset({source}))
    return PathSearchResult(
        source_found=source_found,
        target_found=target_found,
        paths=tuple(paths),
        truncated=truncated,
        expanded_edges=expanded_edges,
    )
