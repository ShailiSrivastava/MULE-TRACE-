"""Transaction-level facts retained independently of analysis results."""

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
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.model_base import Base, UTCDateTime, utc_now
from app.models.types import json_document_type

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.analysis import DetectionAlert
    from app.models.dataset import Dataset, GroundTruthLabel


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "id", name="uq_transactions_dataset_id_id"),
        UniqueConstraint(
            "dataset_id",
            "external_transaction_id",
            name="uq_transactions_dataset_external",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "sender_account_id"],
            ["accounts.dataset_id", "accounts.id"],
            ondelete="RESTRICT",
            name="fk_transactions_sender_account_dataset",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "receiver_account_id"],
            ["accounts.dataset_id", "accounts.id"],
            ondelete="RESTRICT",
            name="fk_transactions_receiver_account_dataset",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_iso_code",
        ),
        CheckConstraint(
            "sender_account_id <> receiver_account_id", name="accounts_distinct"
        ),
        Index("ix_transactions_dataset_occurred", "dataset_id", "occurred_at"),
        Index(
            "ix_transactions_dataset_currency_occurred",
            "dataset_id",
            "currency",
            "occurred_at",
        ),
        Index("ix_transactions_dataset_amount", "dataset_id", "amount"),
        Index(
            "ix_transactions_sender_time",
            "dataset_id",
            "sender_account_id",
            "occurred_at",
        ),
        Index(
            "ix_transactions_receiver_time",
            "dataset_id",
            "receiver_account_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE", name="fk_transactions_dataset"),
        nullable=False,
    )
    sender_account_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    receiver_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    external_transaction_id: Mapped[str | None] = mapped_column(String(160))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[str | None] = mapped_column(String(60))
    channel: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str | None] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", json_document_type(), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="transactions")
    sender_account: Mapped[Account] = relationship(
        back_populates="outgoing_transactions",
        primaryjoin="and_(Account.id == foreign(Transaction.sender_account_id), "
        "Account.dataset_id == Transaction.dataset_id)",
        foreign_keys="Transaction.sender_account_id",
    )
    receiver_account: Mapped[Account] = relationship(
        back_populates="incoming_transactions",
        primaryjoin="and_(Account.id == foreign(Transaction.receiver_account_id), "
        "Account.dataset_id == Transaction.dataset_id)",
        foreign_keys="Transaction.receiver_account_id",
    )
    ground_truth_labels: Mapped[list[GroundTruthLabel]] = relationship(
        back_populates="transaction",
        primaryjoin="and_(Transaction.id == foreign(GroundTruthLabel.transaction_id), "
        "Transaction.dataset_id == GroundTruthLabel.dataset_id)",
        passive_deletes="all",
    )
    detection_alerts: Mapped[list[DetectionAlert]] = relationship(
        back_populates="transaction",
        primaryjoin="and_(Transaction.id == foreign(DetectionAlert.transaction_id), "
        "Transaction.dataset_id == DetectionAlert.dataset_id)",
        passive_deletes="all",
    )
