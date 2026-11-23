from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bank_code: Mapped[str] = mapped_column(String(32), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    outgoing_transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", foreign_keys="Transaction.source_account_id", back_populates="source_account"
    )
    incoming_transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", foreign_keys="Transaction.destination_account_id", back_populates="destination_account"
    )
    alerts: Mapped[list["DetectionAlert"]] = relationship("DetectionAlert", back_populates="account")
    risk_scores: Mapped[list["RiskScore"]] = relationship("RiskScore", back_populates="account")
    case_links: Mapped[list["CaseAccount"]] = relationship("CaseAccount", back_populates="account")
