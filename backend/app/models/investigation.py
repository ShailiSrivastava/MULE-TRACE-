"""Investigation cases and dataset-safe account/alert memberships."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
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
from app.models.types import json_document_type

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.analysis import DetectionAlert
    from app.models.dataset import Dataset
    from app.models.user import User


class InvestigationCase(Base):
    __tablename__ = "investigation_cases"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "id", name="uq_investigation_cases_dataset_id_id"
        ),
        CheckConstraint(
            "status IN ('open', 'in_review', 'resolved', 'closed')", name="status_valid"
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')", name="priority_valid"
        ),
        CheckConstraint(
            "closed_at IS NULL OR closed_at >= opened_at", name="closed_after_opened"
        ),
        Index("ix_investigation_cases_dataset_status", "dataset_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "datasets.id", ondelete="RESTRICT", name="fk_investigation_cases_dataset"
        ),
        nullable=False,
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_investigation_cases_user"),
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default=text("'open'")
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium", server_default=text("'medium'")
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", json_document_type(), nullable=False, default=dict
    )
    opened_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    dataset: Mapped[Dataset] = relationship(back_populates="investigation_cases")
    created_by: Mapped[User | None] = relationship(
        back_populates="created_cases", foreign_keys=[created_by_id]
    )
    account_links: Mapped[list[CaseAccount]] = relationship(
        back_populates="investigation_case",
        primaryjoin="and_(InvestigationCase.id == foreign(CaseAccount.case_id), "
        "InvestigationCase.dataset_id == CaseAccount.dataset_id)",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    alert_links: Mapped[list[CaseAlert]] = relationship(
        back_populates="investigation_case",
        primaryjoin="and_(InvestigationCase.id == foreign(CaseAlert.case_id), "
        "InvestigationCase.dataset_id == CaseAlert.dataset_id)",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class CaseAccount(Base):
    __tablename__ = "case_accounts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "case_id"],
            ["investigation_cases.dataset_id", "investigation_cases.id"],
            ondelete="CASCADE",
            name="fk_case_accounts_case_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "account_id"],
            ["accounts.dataset_id", "accounts.id"],
            ondelete="RESTRICT",
            name="fk_case_accounts_account_dataset",
        ),
        ForeignKeyConstraint(
            ["added_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_case_accounts_added_by_user",
        ),
        PrimaryKeyConstraint("case_id", "account_id", name="pk_case_accounts"),
        Index("ix_case_accounts_dataset_account", "dataset_id", "account_id"),
    )

    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    added_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )

    investigation_case: Mapped[InvestigationCase] = relationship(
        back_populates="account_links",
        primaryjoin="and_(InvestigationCase.id == foreign(CaseAccount.case_id), "
        "InvestigationCase.dataset_id == CaseAccount.dataset_id)",
    )
    account: Mapped[Account] = relationship(
        back_populates="case_links",
        primaryjoin="and_(Account.id == foreign(CaseAccount.account_id), "
        "Account.dataset_id == CaseAccount.dataset_id)",
    )
    added_by: Mapped[User | None] = relationship(foreign_keys=[added_by_id])


class CaseAlert(Base):
    __tablename__ = "case_alerts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "case_id"],
            ["investigation_cases.dataset_id", "investigation_cases.id"],
            ondelete="CASCADE",
            name="fk_case_alerts_case_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "alert_id"],
            ["detection_alerts.dataset_id", "detection_alerts.id"],
            ondelete="RESTRICT",
            name="fk_case_alerts_alert_dataset",
        ),
        PrimaryKeyConstraint("case_id", "alert_id", name="pk_case_alerts"),
        Index("ix_case_alerts_dataset_alert", "dataset_id", "alert_id"),
    )

    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    alert_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)

    investigation_case: Mapped[InvestigationCase] = relationship(
        back_populates="alert_links",
        primaryjoin="and_(InvestigationCase.id == foreign(CaseAlert.case_id), "
        "InvestigationCase.dataset_id == CaseAlert.dataset_id)",
    )
    alert: Mapped[DetectionAlert] = relationship(
        back_populates="case_links",
        primaryjoin="and_(DetectionAlert.id == foreign(CaseAlert.alert_id), "
        "DetectionAlert.dataset_id == CaseAlert.dataset_id)",
    )
