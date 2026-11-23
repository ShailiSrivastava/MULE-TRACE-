"""Durable model-version metadata; fitted artifacts remain process-local."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.model_base import Base, UTCDateTime, utc_now
from app.models.types import json_document_type


class MLModelRegistryRecord(Base):
    """Reproducibility metadata without raw financial rows or pickle blobs."""

    __tablename__ = "ml_model_registry"
    __table_args__ = (
        UniqueConstraint("model_name", "model_version", name="uq_ml_model_name_version"),
        CheckConstraint(
            "entity_type IN ('ACCOUNT', 'TRANSACTION')", name="entity_type_valid"
        ),
        CheckConstraint(
            "status IN ('TRAINED', 'EVALUATED', 'ARCHIVED')", name="status_valid"
        ),
        CheckConstraint("training_sample_count >= 2", name="training_sample_count_minimum"),
        Index("ix_ml_model_registry_dataset_status", "training_dataset_id", "status"),
        Index("ix_ml_model_registry_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    training_dataset_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="SET NULL", name="fk_ml_model_registry_dataset"),
    )
    training_timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    training_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_names: Mapped[list[str]] = mapped_column(
        json_document_type(), nullable=False
    )
    model_parameters: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False
    )
    preprocessing_config: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False
    )
    evaluation_metrics: Mapped[dict[str, Any] | None] = mapped_column(
        json_document_type()
    )
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ml_model_registry_user"),
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
