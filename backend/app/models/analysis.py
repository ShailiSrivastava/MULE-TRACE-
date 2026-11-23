"""Analysis runs, algorithm detections, and per-account risk scores."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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
    from app.models.dataset import Dataset
    from app.models.finding import DetectionFinding
    from app.models.investigation import CaseAlert
    from app.models.transaction import Transaction
    from app.models.user import User


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        UniqueConstraint("dataset_id", "id", name="uq_analysis_jobs_dataset_id_id"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="status_valid",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="progress_percent_range",
        ),
        CheckConstraint("retry_count >= 0", name="retry_count_nonnegative"),
        UniqueConstraint(
            "dataset_id", "created_by_id", "idempotency_key",
            name="uq_analysis_jobs_owner_idempotency",
        ),
        UniqueConstraint("task_id", name="uq_analysis_jobs_task_id"),
        Index(
            "ix_analysis_jobs_dataset_status_created",
            "dataset_id",
            "status",
            "created_at",
        ),
        Index("ix_analysis_jobs_status_heartbeat", "status", "heartbeat_at"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE", name="fk_analysis_jobs_dataset"),
        nullable=False,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_analysis_jobs_user"),
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    parameters: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict
    )
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(json_document_type())
    error_message: Mapped[str | None] = mapped_column(Text)
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    current_stage: Mapped[str | None] = mapped_column(String(80))
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    task_id: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now,
        server_default=func.now(),
    )

    dataset: Mapped[Dataset] = relationship(back_populates="analysis_jobs")
    created_by: Mapped[User | None] = relationship(
        back_populates="created_analysis_jobs", foreign_keys=[created_by_id]
    )
    detection_alerts: Mapped[list[DetectionAlert]] = relationship(
        back_populates="analysis_job",
        primaryjoin="and_(AnalysisJob.id == foreign(DetectionAlert.analysis_job_id), "
        "AnalysisJob.dataset_id == DetectionAlert.dataset_id)",
        passive_deletes="all",
    )
    risk_assessments: Mapped[list[RiskAssessment]] = relationship(
        back_populates="analysis_job",
        primaryjoin="and_(AnalysisJob.id == foreign(RiskAssessment.analysis_job_id), "
        "AnalysisJob.dataset_id == RiskAssessment.dataset_id)",
        passive_deletes="all",
    )


class DetectionAlert(Base):
    """Detection output, kept independent from ground-truth labels."""

    __tablename__ = "detection_alerts"
    __table_args__ = (
        UniqueConstraint("dataset_id", "id", name="uq_detection_alerts_dataset_id_id"),
        ForeignKeyConstraint(
            ["dataset_id", "analysis_job_id"],
            ["analysis_jobs.dataset_id", "analysis_jobs.id"],
            ondelete="CASCADE",
            name="fk_detection_alerts_analysis_job_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "transaction_id"],
            ["transactions.dataset_id", "transactions.id"],
            ondelete="CASCADE",
            name="fk_detection_alerts_transaction_dataset",
        ),
        UniqueConstraint(
            "analysis_job_id",
            "transaction_id",
            "rule_code",
            name="uq_detection_job_transaction_rule",
        ),
        CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name="severity_valid",
        ),
        CheckConstraint(
            "status IN ('open', 'reviewed', 'confirmed', 'false_positive', 'resolved')",
            name="status_valid",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)", name="score_range"
        ),
        Index("ix_detection_alerts_dataset_status", "dataset_id", "status"),
        Index("ix_detection_alerts_dataset_severity", "dataset_id", "severity"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    transaction_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium", server_default=text("'medium'")
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="open", server_default=text("'open'")
    )
    score: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    evidence: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict
    )
    detected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )

    analysis_job: Mapped[AnalysisJob] = relationship(
        back_populates="detection_alerts",
        primaryjoin="and_(AnalysisJob.id == foreign(DetectionAlert.analysis_job_id), "
        "AnalysisJob.dataset_id == DetectionAlert.dataset_id)",
    )
    transaction: Mapped[Transaction] = relationship(
        back_populates="detection_alerts",
        primaryjoin="and_(Transaction.id == foreign(DetectionAlert.transaction_id), "
        "Transaction.dataset_id == DetectionAlert.dataset_id)",
    )
    case_links: Mapped[list[CaseAlert]] = relationship(
        back_populates="alert",
        primaryjoin="and_(DetectionAlert.id == foreign(CaseAlert.alert_id), "
        "DetectionAlert.dataset_id == CaseAlert.dataset_id)",
        passive_deletes="all",
    )


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "analysis_job_id"],
            ["analysis_jobs.dataset_id", "analysis_jobs.id"],
            ondelete="CASCADE",
            name="fk_risk_assessments_analysis_job_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "account_id"],
            ["accounts.dataset_id", "accounts.id"],
            ondelete="CASCADE",
            name="fk_risk_assessments_account_dataset",
        ),
        UniqueConstraint(
            "analysis_job_id",
            "account_id",
            "scoring_model_version",
            name="uq_risk_assessments_job_account_version",
        ),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="risk_level_valid",
        ),
        CheckConstraint(
            "(account_id IS NOT NULL AND finding_id IS NULL) OR "
            "(account_id IS NULL AND finding_id IS NOT NULL)",
            name="assessment_scope_exactly_one",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            ondelete="CASCADE",
            name="fk_risk_assessments_finding_dataset",
        ),
        Index("ix_risk_assessments_dataset_account", "dataset_id", "account_id"),
        Index("ix_risk_assessments_dataset_finding", "dataset_id", "finding_id"),
        UniqueConstraint(
            "analysis_job_id",
            "finding_id",
            "scoring_model_version",
            name="uq_risk_assessments_job_finding_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    analysis_job_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    account_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    finding_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    score: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    scoring_model_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="1.0"
    )
    score_components: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict
    )
    rationale: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict
    )
    assessed_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )

    analysis_job: Mapped[AnalysisJob] = relationship(
        back_populates="risk_assessments",
        primaryjoin="and_(AnalysisJob.id == foreign(RiskAssessment.analysis_job_id), "
        "AnalysisJob.dataset_id == RiskAssessment.dataset_id)",
    )
    account: Mapped[Account | None] = relationship(
        back_populates="risk_assessments",
        primaryjoin="and_(Account.id == foreign(RiskAssessment.account_id), "
        "Account.dataset_id == RiskAssessment.dataset_id)",
    )
    finding: Mapped[DetectionFinding | None] = relationship(
        back_populates="risk_assessments",
        primaryjoin="and_(DetectionFinding.id == foreign(RiskAssessment.finding_id), "
        "DetectionFinding.dataset_id == RiskAssessment.dataset_id)",
    )
