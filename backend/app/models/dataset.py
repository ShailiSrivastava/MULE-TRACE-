"""Dataset ownership and isolated ground-truth labels."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.model_base import Base, UTCDateTime, utc_now
from app.models.types import json_document_type

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.analysis import AnalysisJob
    from app.models.import_job import ImportJob
    from app.models.investigation import InvestigationCase
    from app.models.transaction import Transaction
    from app.models.user import User


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_datasets_owner_name"),
        UniqueConstraint("id", "owner_id", name="uq_datasets_id_owner"),
        CheckConstraint(
            "status IN ('draft', 'ready', 'failed', 'archived')",
            name="status_valid",
        ),
        Index("ix_datasets_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_datasets_owner_user"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default=text("'draft'")
    )
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", json_document_type(), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    owner: Mapped[User] = relationship(back_populates="datasets")
    accounts: Mapped[list[Account]] = relationship(
        back_populates="dataset", passive_deletes="all"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="dataset", passive_deletes="all"
    )
    ground_truth_labels: Mapped[list[GroundTruthLabel]] = relationship(
        back_populates="dataset", passive_deletes="all"
    )
    analysis_jobs: Mapped[list[AnalysisJob]] = relationship(
        back_populates="dataset", passive_deletes="all"
    )
    investigation_cases: Mapped[list[InvestigationCase]] = relationship(
        back_populates="dataset", passive_deletes="all"
    )
    import_jobs: Mapped[list[ImportJob]] = relationship(
        back_populates="dataset", passive_deletes="all"
    )


class GroundTruthLabel(Base):
    """Curated or synthetic labels kept separate from algorithm detections."""

    __tablename__ = "ground_truth_labels"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            ondelete="CASCADE",
            name="fk_ground_truth_labels_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "transaction_id"],
            ["transactions.dataset_id", "transactions.id"],
            ondelete="CASCADE",
            name="fk_ground_truth_labels_transaction_dataset",
        ),
        UniqueConstraint(
            "dataset_id",
            "transaction_id",
            "label_scheme",
            name="uq_ground_truth_transaction_scheme",
        ),
        CheckConstraint(
            "source IN ('synthetic', 'curated', 'imported')", name="source_valid"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        Index("ix_ground_truth_labels_dataset_label", "dataset_id", "label_code"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    label_code: Mapped[str] = mapped_column(String(80), nullable=False)
    label_scheme: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="muletrace_v1",
        server_default=text("'muletrace_v1'"),
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="curated", server_default=text("'curated'")
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    labeled_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ground_truth_labels_user"),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", json_document_type(), nullable=False, default=dict
    )
    labeled_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="ground_truth_labels")
    transaction: Mapped[Transaction] = relationship(
        back_populates="ground_truth_labels",
        primaryjoin="and_(foreign(GroundTruthLabel.transaction_id) == Transaction.id, "
        "GroundTruthLabel.dataset_id == Transaction.dataset_id)",
    )
    labeled_by: Mapped[User | None] = relationship(foreign_keys=[labeled_by_id])
