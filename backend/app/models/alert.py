from datetime import datetime, timezone

from sqlalchemy import String, Float, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DetectionAlert(Base):
    __tablename__ = "detection_alerts"
    __table_args__ = (Index("ix_detection_alerts_severity_status", "severity", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_ref: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    pattern_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False)
    description: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    account: Mapped["Account"] = relationship("Account", back_populates="alerts")
    transaction: Mapped["Transaction | None"] = relationship("Transaction")
