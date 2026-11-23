"""Dataset-scoped account persistence and query workflows."""

from __future__ import annotations

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


class AccountNotFound(LookupError):
    """Raised when an account is absent from an owned dataset."""


def _transaction_count_expression():
    return (
        select(func.count(Transaction.id))
        .where(
            Transaction.dataset_id == Account.dataset_id,
            or_(
                Transaction.sender_account_id == Account.id,
                Transaction.receiver_account_id == Account.id,
            ),
        )
        .correlate(Account)
        .scalar_subquery()
    )


def _account_conditions(
    dataset_id: UUID,
    *,
    account_type: str | None,
    country_code: str | None,
    external_id: str | None,
) -> list[Any]:
    conditions: list[Any] = [Account.dataset_id == dataset_id]
    if account_type is not None:
        conditions.append(Account.account_type == account_type)
    if country_code is not None:
        conditions.append(Account.country_code == country_code.upper())
    if external_id is not None:
        conditions.append(Account.external_id == external_id)
    return conditions


def create_account(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    fields: dict[str, Any],
) -> tuple[Account, int]:
    require_owned_dataset(db, dataset_id, actor.id)
    account = Account(
        dataset_id=dataset_id,
        external_id=fields["external_id"],
        account_type=fields.get("account_type"),
        institution_code=fields.get("institution_code"),
        country_code=fields.get("country_code"),
        metadata_json=fields.get("metadata", {}),
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc

    record_resource_audit(
        db,
        actor_id=actor.id,
        event_type="account.created",
        entity_type="account",
        entity_id=account.id,
        dataset_id=dataset_id,
        fields=list(fields),
    )
    try:
        db.commit()
        db.refresh(account)
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc
    return account, 0


def get_account(
    db: Session, *, dataset_id: UUID, account_id: UUID, actor: User
) -> tuple[Account, int]:
    require_owned_dataset(db, dataset_id, actor.id)
    row = db.execute(
        select(
            Account, _transaction_count_expression().label("transaction_count")
        ).where(Account.dataset_id == dataset_id, Account.id == account_id)
    ).one_or_none()
    if row is None:
        raise AccountNotFound
    return row[0], int(row[1])


def list_accounts(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    account_type: str | None = None,
    country_code: str | None = None,
    external_id: str | None = None,
) -> tuple[list[tuple[Account, int]], int]:
    require_owned_dataset(db, dataset_id, actor.id)
    conditions = _account_conditions(
        dataset_id,
        account_type=account_type,
        country_code=country_code,
        external_id=external_id,
    )
    total = db.scalar(select(func.count(Account.id)).where(*conditions)) or 0
    rows = db.execute(
        select(Account, _transaction_count_expression().label("transaction_count"))
        .where(*conditions)
        .order_by(Account.created_at.desc(), Account.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [(row[0], int(row[1])) for row in rows], int(total)


def update_account(
    db: Session,
    *,
    dataset_id: UUID,
    account_id: UUID,
    actor: User,
    fields: dict[str, Any],
) -> tuple[Account, int]:
    require_owned_dataset(db, dataset_id, actor.id)
    account = db.scalar(
        select(Account).where(
            Account.dataset_id == dataset_id,
            Account.id == account_id,
        )
    )
    if account is None:
        raise AccountNotFound

    for field, value in fields.items():
        setattr(account, "metadata_json" if field == "metadata" else field, value)
    record_resource_audit(
        db,
        actor_id=actor.id,
        event_type="account.updated",
        entity_type="account",
        entity_id=account.id,
        dataset_id=dataset_id,
        fields=list(fields),
    )
    try:
        db.commit()
        db.refresh(account)
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc
    _, transaction_count = get_account(
        db, dataset_id=dataset_id, account_id=account_id, actor=actor
    )
    return account, transaction_count
