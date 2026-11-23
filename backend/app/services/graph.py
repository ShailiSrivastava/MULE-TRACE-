"""Dataset-scoped database loading for the pure financial graph engine."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.builder import TransactionGraph, build_transaction_graph
from app.graph.models import (
    DEFAULT_GRAPH_LIMITS,
    AccountRecord,
    GraphFilters,
    GraphLimits,
    TransactionRecord,
)
from app.models import Account, Transaction
from app.services.dataset_access import require_owned_dataset


def build_owned_dataset_graph(
    db: Session,
    *,
    dataset_id: UUID,
    owner_id: UUID,
    filters: GraphFilters | None = None,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> TransactionGraph:
    """Load one owned dataset into a bounded graph without ORM relationship loads.

    The ownership check runs before either record query. Queries are restricted
    to selected columns, dataset ID, requested filters, and ``limit + 1`` rows so
    an oversized dataset is rejected instead of copied without bounds.
    """

    require_owned_dataset(db, dataset_id, owner_id)
    filters = filters or GraphFilters()

    account_statement = select(
        Account.id,
        Account.dataset_id,
        Account.account_type,
        Account.institution_code,
        Account.country_code,
    ).where(Account.dataset_id == dataset_id)
    if filters.account_ids is not None:
        account_statement = account_statement.where(Account.id.in_(filters.account_ids))
    account_statement = (
        account_statement.order_by(Account.id)
        .limit(limits.max_accounts + 1)
        .execution_options(yield_per=1_000)
    )

    transaction_statement = select(
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
    ).where(Transaction.dataset_id == dataset_id)
    if filters.start_at is not None:
        transaction_statement = transaction_statement.where(
            Transaction.occurred_at >= filters.start_at
        )
    if filters.end_at is not None:
        transaction_statement = transaction_statement.where(
            Transaction.occurred_at < filters.end_at
        )
    if filters.currency is not None:
        transaction_statement = transaction_statement.where(
            Transaction.currency == filters.currency
        )
    if filters.minimum_amount is not None:
        transaction_statement = transaction_statement.where(
            Transaction.amount >= filters.minimum_amount
        )
    if filters.maximum_amount is not None:
        transaction_statement = transaction_statement.where(
            Transaction.amount <= filters.maximum_amount
        )
    if filters.account_ids is not None:
        transaction_statement = transaction_statement.where(
            Transaction.sender_account_id.in_(filters.account_ids),
            Transaction.receiver_account_id.in_(filters.account_ids),
        )
    transaction_statement = (
        transaction_statement.order_by(Transaction.id)
        .limit(limits.max_transactions + 1)
        .execution_options(yield_per=1_000)
    )

    def account_records():
        result = db.execute(account_statement)
        try:
            for row in result:
                yield AccountRecord(
                    id=row.id,
                    dataset_id=row.dataset_id,
                    account_type=row.account_type,
                    institution_code=row.institution_code,
                    country_code=row.country_code,
                )
        finally:
            result.close()

    def transaction_records():
        result = db.execute(transaction_statement)
        try:
            for row in result:
                yield TransactionRecord(
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
        finally:
            result.close()

    return build_transaction_graph(
        dataset_id,
        account_records(),
        transaction_records(),
        filters=filters,
        limits=limits,
    )
