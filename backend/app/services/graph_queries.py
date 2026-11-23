"""Owner-scoped SQL loading for frontend graph endpoints."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.graph.builder import TransactionGraph, build_transaction_graph
from app.graph.metrics import account_metrics
from app.graph.models import (
    DEFAULT_GRAPH_LIMITS,
    AccountRecord,
    GraphFilters,
    GraphLimitExceeded,
    GraphLimits,
    PathSearchResult,
    TransactionRecord,
)
from app.graph.paths import find_bounded_paths
from app.models import Account, Transaction
from app.services.dataset_access import require_owned_dataset

ACCOUNT_CHUNK_SIZE = 500


class AccountGraphNotFound(LookupError):
    """The account does not exist in the requested dataset."""


def _transaction_predicates(dataset_id: UUID, filters: GraphFilters) -> list:
    conditions = [Transaction.dataset_id == dataset_id]
    if filters.start_at is not None:
        conditions.append(Transaction.occurred_at >= filters.start_at)
    if filters.end_at is not None:
        conditions.append(Transaction.occurred_at < filters.end_at)
    if filters.currency is not None:
        conditions.append(Transaction.currency == filters.currency)
    if filters.minimum_amount is not None:
        conditions.append(Transaction.amount >= filters.minimum_amount)
    if filters.maximum_amount is not None:
        conditions.append(Transaction.amount <= filters.maximum_amount)
    return conditions


def _account_record(row) -> AccountRecord:
    return AccountRecord(
        id=row.id,
        dataset_id=row.dataset_id,
        account_type=row.account_type,
        institution_code=row.institution_code,
        country_code=row.country_code,
    )


def _transaction_record(row) -> TransactionRecord:
    return TransactionRecord(
        id=row.id,
        dataset_id=row.dataset_id,
        sender_account_id=row.sender_account_id,
        receiver_account_id=row.receiver_account_id,
        amount=row.amount,
        currency=row.currency,
        occurred_at=row.occurred_at,
        transaction_type=row.transaction_type,
        channel=row.channel,
        status=row.status,
    )


def _chunks(values: Iterable[UUID], size: int = ACCOUNT_CHUNK_SIZE):
    items = sorted(set(values), key=str)
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def _load_account_records(
    db: Session,
    *,
    dataset_id: UUID,
    account_ids: set[UUID],
    limits: GraphLimits,
) -> list[AccountRecord]:
    if len(account_ids) > limits.max_accounts:
        raise GraphLimitExceeded(
            f"Graph neighborhood exceeds the {limits.max_accounts}-account limit."
        )
    records: dict[UUID, AccountRecord] = {}
    for account_chunk in _chunks(account_ids):
        rows = db.execute(
            select(
                Account.id,
                Account.dataset_id,
                Account.account_type,
                Account.institution_code,
                Account.country_code,
            ).where(
                Account.dataset_id == dataset_id,
                Account.id.in_(account_chunk),
            )
        )
        records.update((row.id, _account_record(row)) for row in rows)
    return [records[account_id] for account_id in sorted(records, key=str)]


def list_graph_nodes(
    db: Session,
    *,
    dataset_id: UUID,
    owner_id: UUID,
    page: int,
    page_size: int,
    account_type: str | None = None,
    country_code: str | None = None,
    institution_code: str | None = None,
) -> tuple[list, int]:
    """Return only graph-safe account columns using one bounded page query."""

    require_owned_dataset(db, dataset_id, owner_id)
    conditions = [Account.dataset_id == dataset_id]
    if account_type is not None:
        conditions.append(Account.account_type == account_type)
    if country_code is not None:
        conditions.append(Account.country_code == country_code.upper())
    if institution_code is not None:
        conditions.append(Account.institution_code == institution_code)
    total = int(
        db.scalar(select(func.count(Account.id)).where(*conditions)) or 0
    )
    rows = db.execute(
        select(
            Account.id,
            Account.dataset_id,
            Account.account_type,
            Account.institution_code,
            Account.country_code,
        )
        .where(*conditions)
        .order_by(Account.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return rows, total


def list_graph_edges(
    db: Session,
    *,
    dataset_id: UUID,
    owner_id: UUID,
    filters: GraphFilters,
    page: int,
    page_size: int,
    account_id: UUID | None = None,
    source_account_id: UUID | None = None,
    target_account_id: UUID | None = None,
    sort_by: str = "occurred_at",
    sort_order: str = "desc",
) -> tuple[list, int]:
    """Return paginated transaction rows without constructing a full graph."""

    require_owned_dataset(db, dataset_id, owner_id)
    conditions = _transaction_predicates(dataset_id, filters)
    if account_id is not None:
        conditions.append(
            or_(
                Transaction.sender_account_id == account_id,
                Transaction.receiver_account_id == account_id,
            )
        )
    if source_account_id is not None:
        conditions.append(Transaction.sender_account_id == source_account_id)
    if target_account_id is not None:
        conditions.append(Transaction.receiver_account_id == target_account_id)
    total = int(
        db.scalar(select(func.count(Transaction.id)).where(*conditions)) or 0
    )
    sort_columns = {
        "occurred_at": Transaction.occurred_at,
        "amount": Transaction.amount,
        "currency": Transaction.currency,
    }
    order_column = sort_columns[sort_by]
    ordering = order_column.asc() if sort_order == "asc" else order_column.desc()
    rows = db.execute(
        select(
            Transaction.id,
            Transaction.dataset_id,
            Transaction.sender_account_id,
            Transaction.receiver_account_id,
            Transaction.amount,
            Transaction.currency,
            Transaction.occurred_at,
            Transaction.transaction_type,
            Transaction.channel,
            Transaction.status,
        )
        .where(*conditions)
        .order_by(ordering, Transaction.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return rows, total


def graph_overview(
    db: Session,
    *,
    dataset_id: UUID,
    owner_id: UUID,
    filters: GraphFilters,
) -> dict:
    """Compute bounded SQL aggregates; no NetworkX graph is built here."""

    require_owned_dataset(db, dataset_id, owner_id)
    node_count = int(
        db.scalar(
            select(func.count(Account.id)).where(Account.dataset_id == dataset_id)
        )
        or 0
    )
    conditions = _transaction_predicates(dataset_id, filters)
    edge_count = int(
        db.scalar(select(func.count(Transaction.id)).where(*conditions)) or 0
    )
    distinct_pairs = (
        select(
            Transaction.sender_account_id,
            Transaction.receiver_account_id,
        )
        .where(
            *conditions,
            Transaction.sender_account_id != Transaction.receiver_account_id,
        )
        .distinct()
        .subquery()
    )
    pair_count = int(
        db.scalar(select(func.count()).select_from(distinct_pairs)) or 0
    )
    density = (
        pair_count / (node_count * (node_count - 1)) if node_count > 1 else 0.0
    )
    totals = db.execute(
        select(
            Transaction.currency,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
        )
        .where(*conditions)
        .group_by(Transaction.currency)
        .order_by(Transaction.currency)
    ).all()
    return {
        "dataset_id": dataset_id,
        "node_count": node_count,
        "edge_count": edge_count,
        "directed_density": density,
        "currency_totals": [
            {
                "currency": currency,
                "transaction_count": int(count),
                "total_amount": total_amount,
            }
            for currency, count, total_amount in totals
        ],
        "filters": filters.metadata(),
    }


def account_network_metrics(
    db: Session,
    *,
    dataset_id: UUID,
    owner_id: UUID,
    account_id: UUID,
    filters: GraphFilters,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
):
    """Build a bounded one-hop graph and reuse Phase 7's exact metric semantics."""

    require_owned_dataset(db, dataset_id, owner_id)
    root = db.execute(
        select(
            Account.id,
            Account.dataset_id,
            Account.account_type,
            Account.institution_code,
            Account.country_code,
        ).where(Account.dataset_id == dataset_id, Account.id == account_id)
    ).first()
    if root is None:
        raise AccountGraphNotFound

    rows = db.execute(
        select(
            Transaction.id,
            Transaction.dataset_id,
            Transaction.sender_account_id,
            Transaction.receiver_account_id,
            Transaction.amount,
            Transaction.currency,
            Transaction.occurred_at,
            Transaction.transaction_type,
            Transaction.channel,
            Transaction.status,
        )
        .where(
            *_transaction_predicates(dataset_id, filters),
            or_(
                Transaction.sender_account_id == account_id,
                Transaction.receiver_account_id == account_id,
            ),
        )
        .order_by(Transaction.id)
        .limit(limits.max_transactions + 1)
    ).all()
    if len(rows) > limits.max_transactions:
        raise GraphLimitExceeded(
            f"Account network exceeds the {limits.max_transactions}-transaction limit."
        )
    records = [_transaction_record(row) for row in rows]
    account_ids = {account_id}
    for record in records:
        account_ids.add(record.sender_account_id)
        account_ids.add(record.receiver_account_id)
    accounts = _load_account_records(
        db,
        dataset_id=dataset_id,
        account_ids=account_ids,
        limits=limits,
    )
    graph = build_transaction_graph(
        dataset_id, accounts, records, filters=filters, limits=limits
    )
    return account_metrics(graph, account_id)


def _fetch_frontier_transactions(
    db: Session,
    *,
    dataset_id: UUID,
    frontier: set[UUID],
    filters: GraphFilters,
    mode: str,
    limits: GraphLimits,
) -> list[TransactionRecord]:
    if not frontier:
        return []
    records: dict[UUID, TransactionRecord] = {}
    scanned = 0
    scan_cap = limits.max_transactions * (2 if mode == "both" else 1)
    for account_chunk in _chunks(frontier):
        if mode == "outgoing":
            direction = Transaction.sender_account_id.in_(account_chunk)
        elif mode == "incoming":
            direction = Transaction.receiver_account_id.in_(account_chunk)
        else:
            direction = or_(
                Transaction.sender_account_id.in_(account_chunk),
                Transaction.receiver_account_id.in_(account_chunk),
            )
        rows = db.execute(
            select(
                Transaction.id,
                Transaction.dataset_id,
                Transaction.sender_account_id,
                Transaction.receiver_account_id,
                Transaction.amount,
                Transaction.currency,
                Transaction.occurred_at,
                Transaction.transaction_type,
                Transaction.channel,
                Transaction.status,
            )
            .where(*_transaction_predicates(dataset_id, filters), direction)
            .order_by(Transaction.id)
            .limit(scan_cap - scanned + 1)
        ).all()
        scanned += len(rows)
        records.update((row.id, _transaction_record(row)) for row in rows)
        if scanned > scan_cap or len(records) > limits.max_transactions:
            raise GraphLimitExceeded(
                f"Graph neighborhood exceeds the {limits.max_transactions}-transaction limit."
            )
    return [records[item] for item in sorted(records, key=str)]


def account_neighborhood_graph(
    db: Session,
    *,
    dataset_id: UUID,
    owner_id: UUID,
    account_id: UUID,
    depth: int,
    direction: str,
    filters: GraphFilters,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> TransactionGraph:
    """Load only breadth-first frontier transactions, then induced local edges."""

    require_owned_dataset(db, dataset_id, owner_id)
    root_records = _load_account_records(
        db,
        dataset_id=dataset_id,
        account_ids={account_id},
        limits=limits,
    )
    if not root_records:
        raise AccountGraphNotFound

    selected = {account_id}
    frontier = {account_id}
    for _ in range(depth):
        frontier_records = _fetch_frontier_transactions(
            db,
            dataset_id=dataset_id,
            frontier=frontier,
            filters=filters,
            mode=direction,
            limits=limits,
        )
        neighbors: set[UUID] = set()
        for record in frontier_records:
            if direction in {"incoming", "both"}:
                neighbors.add(record.sender_account_id)
            if direction in {"outgoing", "both"}:
                neighbors.add(record.receiver_account_id)
        next_frontier = neighbors - selected
        selected.update(next_frontier)
        if len(selected) > limits.max_accounts:
            raise GraphLimitExceeded(
                f"Graph neighborhood exceeds the {limits.max_accounts}-account limit."
            )
        frontier = next_frontier
        if not frontier:
            break

    # Neighborhood semantics match Phase 7's induced subgraph: include every
    # filtered transaction whose two endpoints are selected, not only BFS edges.
    induced: dict[UUID, TransactionRecord] = {}
    scanned = 0
    scan_cap = limits.max_transactions * 2
    for account_chunk in _chunks(selected):
        remaining = scan_cap - scanned
        rows = db.execute(
            select(
                Transaction.id,
                Transaction.dataset_id,
                Transaction.sender_account_id,
                Transaction.receiver_account_id,
                Transaction.amount,
                Transaction.currency,
                Transaction.occurred_at,
                Transaction.transaction_type,
                Transaction.channel,
                Transaction.status,
            )
            .where(
                *_transaction_predicates(dataset_id, filters),
                Transaction.sender_account_id.in_(account_chunk),
            )
            .order_by(Transaction.id)
            .limit(remaining + 1)
        ).all()
        scanned += len(rows)
        for row in rows:
            if row.receiver_account_id in selected:
                induced[row.id] = _transaction_record(row)
        if scanned > scan_cap or len(induced) > limits.max_transactions:
            raise GraphLimitExceeded(
                f"Graph neighborhood exceeds the {limits.max_transactions}-transaction limit."
            )

    accounts = _load_account_records(
        db, dataset_id=dataset_id, account_ids=selected, limits=limits
    )
    return build_transaction_graph(
        dataset_id,
        accounts,
        induced.values(),
        filters=filters,
        limits=limits,
    )


def dataset_bounded_paths(
    db: Session,
    *,
    dataset_id: UUID,
    owner_id: UUID,
    source_account_id: UUID,
    target_account_id: UUID,
    filters: GraphFilters,
    max_hops: int,
    max_paths: int,
    max_expansions: int,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> PathSearchResult:
    """Load the source's bounded reachable subgraph before using Phase 7 DFS."""

    require_owned_dataset(db, dataset_id, owner_id)
    endpoints = _load_account_records(
        db,
        dataset_id=dataset_id,
        account_ids={source_account_id, target_account_id},
        limits=limits,
    )
    endpoint_ids = {record.id for record in endpoints}
    source_found = source_account_id in endpoint_ids
    target_found = target_account_id in endpoint_ids
    if not source_found or not target_found:
        return PathSearchResult(
            source_found=source_found,
            target_found=target_found,
            paths=(),
            truncated=False,
            expanded_edges=0,
        )

    if source_account_id == target_account_id:
        graph = build_transaction_graph(
            dataset_id, endpoints, (), filters=filters, limits=limits
        )
        return find_bounded_paths(
            graph,
            source_account_id,
            target_account_id,
            max_hops=max_hops,
            max_paths=max_paths,
            max_expansions=max_expansions,
            limits=limits,
        )

    selected = {source_account_id}
    frontier = {source_account_id}
    transactions: dict[UUID, TransactionRecord] = {}
    for _ in range(max_hops):
        outgoing = _fetch_frontier_transactions(
            db,
            dataset_id=dataset_id,
            frontier=frontier,
            filters=filters,
            mode="outgoing",
            limits=limits,
        )
        if len(transactions) + len(outgoing) > limits.max_transactions:
            raise GraphLimitExceeded(
                f"Path search exceeds the {limits.max_transactions}-transaction graph limit."
            )
        transactions.update((record.id, record) for record in outgoing)
        neighbors = {
            record.receiver_account_id
            for record in outgoing
            if record.receiver_account_id not in selected
        }
        selected.update(neighbors)
        if len(selected) > limits.max_accounts:
            raise GraphLimitExceeded(
                f"Path search exceeds the {limits.max_accounts}-account graph limit."
            )
        frontier = neighbors
        if not frontier:
            break

    selected.add(target_account_id)
    accounts = _load_account_records(
        db, dataset_id=dataset_id, account_ids=selected, limits=limits
    )
    graph = build_transaction_graph(
        dataset_id,
        accounts,
        transactions.values(),
        filters=filters,
        limits=limits,
    )
    return find_bounded_paths(
        graph,
        source_account_id,
        target_account_id,
        max_hops=max_hops,
        max_paths=max_paths,
        max_expansions=max_expansions,
        limits=limits,
    )
