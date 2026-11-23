"""Shared dataset ownership checks and resource audit event helpers."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.observability import request_id_context
from app.models import AuditLog, Dataset


class DatasetScopeNotFound(LookupError):
    """Raised when a dataset is missing or not owned by the current user."""


class ResourceConflict(ValueError):
    """Raised when a write conflicts with a database integrity constraint."""


def require_owned_dataset(db: Session, dataset_id: UUID, owner_id: UUID) -> None:
    """Hide cross-user dataset existence behind the same not-found outcome."""

    owned_dataset_id = db.scalar(
        select(Dataset.id).where(
            Dataset.id == dataset_id,
            Dataset.owner_id == owner_id,
        )
    )
    if owned_dataset_id is None:
        raise DatasetScopeNotFound


def record_resource_audit(
    db: Session,
    *,
    actor_id: UUID,
    event_type: str,
    entity_type: str,
    entity_id: UUID,
    dataset_id: UUID,
    fields: list[str],
) -> None:
    """Add a resource audit event without persisting domain values."""

    db.add(
        AuditLog(
            actor_user_id=actor_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=request_id_context.get(),
            details={"dataset_id": str(dataset_id), "fields": sorted(fields)},
        )
    )
