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
    from app.models.finding import DetectionFinding
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
        CheckConstraint("length(trim(category)) > 0", name="category_not_blank"),
        Index("ix_investigation_cases_dataset_status", "dataset_id", "status"),
        Index(
            "ix_investigation_cases_dataset_assignee",
            "dataset_id",
            "assigned_to_id",
        ),
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
    assigned_to_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_investigation_cases_assignee"
        ),
    )
    archived_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_investigation_cases_archiver"
        ),
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        String(80), nullable=False, default="general", server_default=text("'general'")
    )
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
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    dataset: Mapped[Dataset] = relationship(back_populates="investigation_cases")
    created_by: Mapped[User | None] = relationship(
        back_populates="created_cases", foreign_keys=[created_by_id]
    )
    assigned_to: Mapped[User | None] = relationship(
        back_populates="assigned_cases", foreign_keys=[assigned_to_id]
    )
    archived_by: Mapped[User | None] = relationship(foreign_keys=[archived_by_id])
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
    finding_links: Mapped[list[CaseFinding]] = relationship(
        back_populates="investigation_case",
        primaryjoin="and_(InvestigationCase.id == foreign(CaseFinding.case_id), "
        "InvestigationCase.dataset_id == CaseFinding.dataset_id)",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notes: Mapped[list[CaseNote]] = relationship(
        back_populates="investigation_case",
        primaryjoin="and_(InvestigationCase.id == foreign(CaseNote.case_id), "
        "InvestigationCase.dataset_id == CaseNote.dataset_id)",
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
        ForeignKeyConstraint(
            ["removed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_case_accounts_removed_by_user",
        ),
        PrimaryKeyConstraint("case_id", "account_id", name="pk_case_accounts"),
        Index("ix_case_accounts_dataset_account", "dataset_id", "account_id"),
    )

    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    added_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    evidence_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        "evidence_snapshot", json_document_type(), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    removed_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))

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


class CaseFinding(Base):
    """A case-to-finding link with a retained evidence snapshot."""

    __tablename__ = "case_findings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "case_id"],
            ["investigation_cases.dataset_id", "investigation_cases.id"],
            ondelete="CASCADE",
            name="fk_case_findings_case_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            ondelete="RESTRICT",
            name="fk_case_findings_finding_dataset",
        ),
        ForeignKeyConstraint(
            ["linked_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_case_findings_linked_by_user",
        ),
        ForeignKeyConstraint(
            ["removed_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_case_findings_removed_by_user",
        ),
        PrimaryKeyConstraint(
            "dataset_id", "case_id", "finding_id", name="pk_case_findings"
        ),
        Index(
            "ix_case_findings_dataset_case_removed",
            "dataset_id",
            "case_id",
            "removed_at",
        ),
        Index("ix_case_findings_dataset_finding", "dataset_id", "finding_id"),
    )

    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    finding_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    linked_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    linked_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(
        json_document_type(), nullable=False, default=dict, server_default=text("'{}'")
    )
    note: Mapped[str | None] = mapped_column(Text)
    removed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    removed_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))

    investigation_case: Mapped[InvestigationCase] = relationship(
        back_populates="finding_links",
        primaryjoin="and_(InvestigationCase.id == foreign(CaseFinding.case_id), "
        "InvestigationCase.dataset_id == CaseFinding.dataset_id)",
    )
    finding: Mapped[DetectionFinding] = relationship(
        primaryjoin="and_(DetectionFinding.id == foreign(CaseFinding.finding_id), "
        "DetectionFinding.dataset_id == CaseFinding.dataset_id)"
    )
    linked_by: Mapped[User | None] = relationship(foreign_keys=[linked_by_id])
    removed_by: Mapped[User | None] = relationship(foreign_keys=[removed_by_id])


class CaseNote(Base):
    """A retained investigation note; deletion is represented by archived_at."""

    __tablename__ = "case_notes"
    __table_args__ = (
        UniqueConstraint("dataset_id", "case_id", "id", name="uq_case_notes_scope_id"),
        ForeignKeyConstraint(
            ["dataset_id", "case_id"],
            ["investigation_cases.dataset_id", "investigation_cases.id"],
            ondelete="CASCADE",
            name="fk_case_notes_case_dataset",
        ),
        ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_case_notes_author_user",
        ),
        Index(
            "ix_case_notes_dataset_case_created", "dataset_id", "case_id", "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    author_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    content: Mapped[str] = mapped_column(Text, nullable=False)
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
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    investigation_case: Mapped[InvestigationCase] = relationship(
        back_populates="notes",
        primaryjoin="and_(InvestigationCase.id == foreign(CaseNote.case_id), "
        "InvestigationCase.dataset_id == CaseNote.dataset_id)",
    )
    author: Mapped[User | None] = relationship(foreign_keys=[author_id])
    revisions: Mapped[list[CaseNoteRevision]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CaseNoteRevision.revision_number",
    )


class CaseNoteRevision(Base):
    """Append-only content snapshot created for the initial and every edited note."""

    __tablename__ = "case_note_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "case_id", "note_id"],
            ["case_notes.dataset_id", "case_notes.case_id", "case_notes.id"],
            ondelete="CASCADE",
            name="fk_case_note_revisions_note_scope",
        ),
        ForeignKeyConstraint(
            ["edited_by_id"],
            ["users.id"],
            ondelete="SET NULL",
            name="fk_case_note_revisions_editor_user",
        ),
        UniqueConstraint(
            "dataset_id",
            "note_id",
            "revision_number",
            name="uq_case_note_revisions_number",
        ),
        CheckConstraint("revision_number >= 1", name="revision_number_positive"),
        Index(
            "ix_case_note_revisions_dataset_case_note",
            "dataset_id",
            "case_id",
            "note_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    case_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    note_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision_number: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    edited_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )

    note: Mapped[CaseNote] = relationship(back_populates="revisions")
    edited_by: Mapped[User | None] = relationship(foreign_keys=[edited_by_id])
