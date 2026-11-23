"""Accounts that participate in dataset transactions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.model_base import Base, UTCDateTime, utc_now
from app.models.types import json_document_type

if TYPE_CHECKING:
    from app.models.analysis import RiskAssessment
    from app.models.dataset import Dataset
    from app.models.investigation import CaseAccount
    from app.models.transaction import Transaction


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("dataset_id", "id", name="uq_accounts_dataset_id_id"),
        UniqueConstraint(
            "dataset_id", "external_id", name="uq_accounts_dataset_external"
        ),
        Index("ix_accounts_dataset_type", "dataset_id", "account_type"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE", name="fk_accounts_dataset"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    account_type: Mapped[str | None] = mapped_column(String(50))
    institution_code: Mapped[str | None] = mapped_column(String(80))
    country_code: Mapped[str | None] = mapped_column(String(2))
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

    dataset: Mapped[Dataset] = relationship(back_populates="accounts")
    outgoing_transactions: Mapped[list[Transaction]] = relationship(
        back_populates="sender_account",
        primaryjoin="and_(Account.id == foreign(Transaction.sender_account_id), "
        "Account.dataset_id == Transaction.dataset_id)",
        foreign_keys="Transaction.sender_account_id",
        passive_deletes="all",
    )
    incoming_transactions: Mapped[list[Transaction]] = relationship(
        back_populates="receiver_account",
        primaryjoin="and_(Account.id == foreign(Transaction.receiver_account_id), "
        "Account.dataset_id == Transaction.dataset_id)",
        foreign_keys="Transaction.receiver_account_id",
        passive_deletes="all",
    )
    risk_assessments: Mapped[list[RiskAssessment]] = relationship(
        back_populates="account",
        primaryjoin="and_(Account.id == foreign(RiskAssessment.account_id), "
        "Account.dataset_id == RiskAssessment.dataset_id)",
        passive_deletes="all",
    )
    case_links: Mapped[list[CaseAccount]] = relationship(
        back_populates="account",
        primaryjoin="and_(Account.id == foreign(CaseAccount.account_id), "
        "Account.dataset_id == CaseAccount.dataset_id)",
        passive_deletes="all",
    )
