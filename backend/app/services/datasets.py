"""Owner-scoped dataset lifecycle and summary query workflows."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Account, Dataset, Transaction, User
from app.services.dataset_access import (
    DatasetScopeNotFound,
    ResourceConflict,
    record_resource_audit,
)


class DatasetNotFound(DatasetScopeNotFound):
    """Raised when a dataset is missing or belongs to another user."""


def _summary_expressions():
    account_count = (
        select(func.count(Account.id))
        .where(Account.dataset_id == Dataset.id)
        .correlate(Dataset)
        .scalar_subquery()
    )
    transaction_count = (
        select(func.count(Transaction.id))
        .where(Transaction.dataset_id == Dataset.id)
        .correlate(Dataset)
        .scalar_subquery()
    )
    return account_count, transaction_count


def _find_dataset(db: Session, *, dataset_id: UUID, owner_id: UUID) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.owner_id == owner_id,
        )
    )
    if dataset is None:
        raise DatasetNotFound
    return dataset


def create_dataset(
    db: Session, *, actor: User, fields: dict[str, Any]
) -> tuple[Dataset, int, int]:
    dataset = Dataset(
        owner_id=actor.id,
        name=fields["name"],
        description=fields.get("description"),
        source=fields.get("source"),
        metadata_json=fields.get("metadata", {}),
    )
    db.add(dataset)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc

    record_resource_audit(
        db,
        actor_id=actor.id,
        event_type="dataset.created",
        entity_type="dataset",
        entity_id=dataset.id,
        dataset_id=dataset.id,
        fields=list(fields),
    )
    try:
        db.commit()
        db.refresh(dataset)
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc
    return dataset, 0, 0


def get_dataset(
    db: Session, *, dataset_id: UUID, actor: User
) -> tuple[Dataset, int, int]:
    dataset = _find_dataset(db, dataset_id=dataset_id, owner_id=actor.id)
    account_count, transaction_count = _summary_expressions()
    counts = db.execute(
        select(account_count, transaction_count).where(Dataset.id == dataset.id)
    ).one()
    return dataset, int(counts[0]), int(counts[1])


def list_datasets(
    db: Session,
    *,
    actor: User,
    page: int,
    page_size: int,
    status: str | None = None,
    is_synthetic: bool | None = None,
) -> tuple[list[tuple[Dataset, int, int]], int]:
    conditions: list[Any] = [Dataset.owner_id == actor.id]
    if status is not None:
        conditions.append(Dataset.status == status)
    if is_synthetic is not None:
        conditions.append(Dataset.is_synthetic.is_(is_synthetic))

    total = db.scalar(select(func.count(Dataset.id)).where(*conditions)) or 0
    account_count, transaction_count = _summary_expressions()
    rows = db.execute(
        select(Dataset, account_count, transaction_count)
        .where(*conditions)
        .order_by(Dataset.created_at.desc(), Dataset.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [(row[0], int(row[1]), int(row[2])) for row in rows], int(total)


def update_dataset(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    fields: dict[str, Any],
) -> tuple[Dataset, int, int]:
    dataset = _find_dataset(db, dataset_id=dataset_id, owner_id=actor.id)
    for field, value in fields.items():
        setattr(dataset, "metadata_json" if field == "metadata" else field, value)
    record_resource_audit(
        db,
        actor_id=actor.id,
        event_type="dataset.updated",
        entity_type="dataset",
        entity_id=dataset.id,
        dataset_id=dataset.id,
        fields=list(fields),
    )
    try:
        db.commit()
        db.refresh(dataset)
    except IntegrityError as exc:
        db.rollback()
        raise ResourceConflict from exc
    return get_dataset(db, dataset_id=dataset_id, actor=actor)
