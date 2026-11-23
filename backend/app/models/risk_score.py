from datetime import datetime, timezone

from sqlalchemy import String, Float, DateTime, ForeignKey, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RiskScore(Base):
    __tablename__ = "risk_scores"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_risk_scores_score_range"),
        Index("ix_risk_scores_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    velocity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    network_centrality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped["Account"] = relationship("Account", back_populates="risk_scores")
