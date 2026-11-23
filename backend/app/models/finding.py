"""Persisted multi-entity detection findings and their audit history."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.model_base import Base, UTCDateTime, utc_now
from app.models.enums import FindingStatus
from app.models.types import json_document_type

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.analysis import AnalysisJob, RiskAssessment
    from app.models.dataset import Dataset
    from app.models.transaction import Transaction
    from app.models.user import User


class DetectionFinding(Base):
    """Canonical current finding; observations retain each analysis snapshot."""

    __tablename__ = "detection_findings"
    __table_args__ = (
        UniqueConstraint("dataset_id", "id", name="uq_detection_findings_dataset_id_id"),
        UniqueConstraint(
            "dataset_id", "deduplication_key", name="uq_detection_findings_dataset_dedup"
        ),
        ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], ondelete="CASCADE", name="fk_detection_findings_dataset"
        ),
        ForeignKeyConstraint(
            ["assigned_to_id"], ["users.id"], ondelete="SET NULL", name="fk_detection_findings_assignee"
        ),
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="severity_valid",
        ),
        CheckConstraint(
            "status IN ('NEW', 'REVIEWING', 'RESOLVED', 'DISMISSED')",
            name="status_valid",
        ),
        CheckConstraint(
            "length(deduplication_key) = 64",
            name="deduplication_key_sha256_length",
        ),
        CheckConstraint(
            "last_detected_at >= first_detected_at",
            name="last_detected_after_first_detected",
        ),
        CheckConstraint(
            "(event_window_start IS NULL AND event_window_end IS NULL) OR "
            "(event_window_start IS NOT NULL AND event_window_end IS NOT NULL "
            "AND event_window_end >= event_window_start)",
            name="event_window_ordered",
        ),
        Index("ix_detection_findings_dataset_status_last", "dataset_id", "status", "last_detected_at"),
        Index("ix_detection_findings_dataset_severity", "dataset_id", "severity"),
        Index("ix_detection_findings_dataset_category", "dataset_id", "category"),
        Index("ix_detection_findings_dataset_assignee", "dataset_id", "assigned_to_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    detector_name: Mapped[str] = mapped_column(String(80), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FindingStatus.NEW.value,
        server_default=text("'NEW'"),
    )
    assigned_to_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    event_window_start: Mapped[datetime | None] = mapped_column(UTCDateTime())
    event_window_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    parameters: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now,
        server_default=func.now(),
    )

    dataset: Mapped[Dataset] = relationship()
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id])
    account_links: Mapped[list[FindingAccount]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", passive_deletes=True
    )
    transaction_links: Mapped[list[FindingTransaction]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", passive_deletes=True
    )
    observations: Mapped[list[FindingObservation]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", passive_deletes=True
    )
    status_history: Mapped[list[FindingStatusHistory]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", passive_deletes=True
    )
    risk_assessments: Mapped[list[RiskAssessment]] = relationship(
        back_populates="finding", passive_deletes="all"
    )


class FindingAccount(Base):
    """Dataset-safe participant link for a finding."""

    __tablename__ = "finding_accounts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            ondelete="CASCADE", name="fk_finding_accounts_finding_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "account_id"],
            ["accounts.dataset_id", "accounts.id"],
            ondelete="RESTRICT", name="fk_finding_accounts_account_dataset",
        ),
        PrimaryKeyConstraint("dataset_id", "finding_id", "account_id", name="pk_finding_accounts"),
        CheckConstraint(
            "relationship_role IN ('participant', 'center', 'source', 'destination', 'intermediary')",
            name="relationship_role_valid",
        ),
        Index("ix_finding_accounts_dataset_account", "dataset_id", "account_id"),
    )

    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    relationship_role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="participant", server_default=text("'participant'")
    )

    finding: Mapped[DetectionFinding] = relationship(back_populates="account_links")
    account: Mapped[Account] = relationship(
        overlaps="account_links,finding"
    )


class FindingTransaction(Base):
    """Dataset-safe transaction reference retained as investigative evidence."""

    __tablename__ = "finding_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            ondelete="CASCADE", name="fk_finding_transactions_finding_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "transaction_id"],
            ["transactions.dataset_id", "transactions.id"],
            ondelete="RESTRICT", name="fk_finding_transactions_transaction_dataset",
        ),
        PrimaryKeyConstraint("dataset_id", "finding_id", "transaction_id", name="pk_finding_transactions"),
        Index("ix_finding_transactions_dataset_transaction", "dataset_id", "transaction_id"),
    )

    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_role: Mapped[str] = mapped_column(
        String(80), nullable=False, default="supporting_evidence",
        server_default=text("'supporting_evidence'"),
    )

    finding: Mapped[DetectionFinding] = relationship(back_populates="transaction_links")
    transaction: Mapped[Transaction] = relationship(
        overlaps="finding,transaction_links"
    )


class FindingObservation(Base):
    """Immutable per-analysis snapshot proving when a finding was observed."""

    __tablename__ = "finding_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            ondelete="CASCADE", name="fk_finding_observations_finding_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "analysis_job_id"],
            ["analysis_jobs.dataset_id", "analysis_jobs.id"],
            ondelete="CASCADE", name="fk_finding_observations_analysis_job_dataset",
        ),
        PrimaryKeyConstraint(
            "dataset_id", "finding_id", "analysis_job_id", name="pk_finding_observations"
        ),
        Index("ix_finding_observations_dataset_job", "dataset_id", "analysis_job_id"),
    )

    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict
    )

    finding: Mapped[DetectionFinding] = relationship(back_populates="observations")
    analysis_job: Mapped[AnalysisJob] = relationship(
        overlaps="finding,observations"
    )


class FindingStatusHistory(Base):
    """Append-only record of lifecycle transitions."""

    __tablename__ = "finding_status_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            ondelete="CASCADE", name="fk_finding_status_history_finding_dataset",
        ),
        ForeignKeyConstraint(
            ["changed_by_id"], ["users.id"], ondelete="SET NULL",
            name="fk_finding_status_history_actor",
        ),
        CheckConstraint(
            "to_status IN ('NEW', 'REVIEWING', 'RESOLVED', 'DISMISSED')",
            name="to_status_valid",
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('NEW', 'REVIEWING', 'RESOLVED', 'DISMISSED')",
            name="from_status_valid",
        ),
        Index("ix_finding_status_history_dataset_finding_time", "dataset_id", "finding_id", "changed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    changed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )

    finding: Mapped[DetectionFinding] = relationship(back_populates="status_history")
    changed_by: Mapped[User | None] = relationship(foreign_keys=[changed_by_id])
