"""Dataset-scoped transaction persistence and query workflows."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, Transaction, User
from app.services.dataset_access import (
    ResourceConflict,
    record_resource_audit,
    require_owned_dataset,
)


class TransactionNotFound(LookupError):
    """Raised when a transaction is absent from an owned dataset."""


class AccountReferenceMismatch(ValueError):
    """Raised when either transfer account is outside the dataset."""


def create_transaction(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    fields: dict[str, Any],
) -> Transaction:
    require_owned_dataset(db, dataset_id, actor.id)
    account_ids = {fields["sender_account_id"], fields["receiver_account_id"]}
    owned_account_ids = set(
        db.scalars(
            select(Account.id).where(
                Account.dataset_id == dataset_id,
                Account.id.in_(account_ids),
            )
        ).all()
    )
    if owned_account_ids != account_ids:
        raise AccountReferenceMismatch

    transaction = Transaction(
        dataset_id=dataset_id,
        sender_account_id=fields["sender_account_id"],
        receiver_account_id=fields["receiver_account_id"],
        external_transaction_id=fields.get("external_transaction_id"),
        amount=fields["amount"],
        currency=fields["currency"],
        transaction_type=fields.get("transaction_type"),
        channel=fields.get("channel"),
        status=fields.get("status"),
        occurred_at=fields["occurred_at"],
        metadata_json=fields.get("metadata", {}),
    )
    db.add(transaction)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc

    record_resource_audit(
        db,
        actor_id=actor.id,
        event_type="transaction.created",
        entity_type="transaction",
        entity_id=transaction.id,
        dataset_id=dataset_id,
        fields=list(fields),
    )
    try:
        db.commit()
        db.refresh(transaction)
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc
    return transaction


def _get_owned_transaction(
    db: Session, *, dataset_id: UUID, transaction_id: UUID, actor: User
) -> Transaction:
    require_owned_dataset(db, dataset_id, actor.id)
    transaction = db.scalar(
        select(Transaction).where(
            Transaction.dataset_id == dataset_id,
            Transaction.id == transaction_id,
        )
    )
    if transaction is None:
        raise TransactionNotFound
    return transaction


def get_transaction(
    db: Session, *, dataset_id: UUID, transaction_id: UUID, actor: User
) -> Transaction:
    return _get_owned_transaction(
        db, dataset_id=dataset_id, transaction_id=transaction_id, actor=actor
    )


def list_transactions(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    account_id: UUID | None = None,
    sender_account_id: UUID | None = None,
    receiver_account_id: UUID | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    currency: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sort_by: str = "occurred_at",
    sort_order: str = "desc",
) -> tuple[list[Transaction], int]:
    require_owned_dataset(db, dataset_id, actor.id)
    conditions: list[Any] = [Transaction.dataset_id == dataset_id]
    if account_id is not None:
        conditions.append(
            or_(
                Transaction.sender_account_id == account_id,
                Transaction.receiver_account_id == account_id,
            )
        )
    if sender_account_id is not None:
        conditions.append(Transaction.sender_account_id == sender_account_id)
    if receiver_account_id is not None:
        conditions.append(Transaction.receiver_account_id == receiver_account_id)
    if min_amount is not None:
        conditions.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        conditions.append(Transaction.amount <= max_amount)
    if currency is not None:
        conditions.append(Transaction.currency == currency.upper())
    if start_at is not None:
        conditions.append(Transaction.occurred_at >= start_at)
    if end_at is not None:
        conditions.append(Transaction.occurred_at <= end_at)

    total = db.scalar(select(func.count(Transaction.id)).where(*conditions)) or 0
    sort_column = {
        "occurred_at": Transaction.occurred_at,
        "created_at": Transaction.created_at,
        "amount": Transaction.amount,
        "currency": Transaction.currency,
    }[sort_by]
    order_by = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    transactions = db.scalars(
        select(Transaction)
        .where(*conditions)
        .order_by(order_by, Transaction.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(transactions), int(total)


def update_transaction(
    db: Session,
    *,
    dataset_id: UUID,
    transaction_id: UUID,
    actor: User,
    fields: dict[str, Any],
) -> Transaction:
    transaction = _get_owned_transaction(
        db, dataset_id=dataset_id, transaction_id=transaction_id, actor=actor
    )
    for field, value in fields.items():
        setattr(
            transaction,
            "metadata_json" if field == "metadata" else field,
            value,
        )
    record_resource_audit(
        db,
        actor_id=actor.id,
        event_type="transaction.updated",
        entity_type="transaction",
        entity_id=transaction.id,
        dataset_id=dataset_id,
        fields=list(fields),
    )
    try:
        db.commit()
        db.refresh(transaction)
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc
    return transaction
