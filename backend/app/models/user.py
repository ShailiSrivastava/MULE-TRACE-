"""User identity, password hash, role, and ownership relationships."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.model_base import Base, UTCDateTime, utc_now
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.analysis import AnalysisJob
    from app.models.audit_log import AuditLog
    from app.models.dataset import Dataset
    from app.models.investigation import InvestigationCase


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("length(email) > 3", name="email_min_length"),
        CheckConstraint(
            "role IN ('ADMIN', 'INVESTIGATOR', 'ANALYST')", name="role_valid"
        ),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    # Nullable only for legacy accounts created before authentication existed.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=UserRole.ANALYST.value,
        server_default=text("'ANALYST'"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    datasets: Mapped[list[Dataset]] = relationship(
        back_populates="owner", passive_deletes="all"
    )
    created_analysis_jobs: Mapped[list[AnalysisJob]] = relationship(
        back_populates="created_by",
        foreign_keys="AnalysisJob.created_by_id",
        passive_deletes="all",
    )
    created_cases: Mapped[list[InvestigationCase]] = relationship(
        back_populates="created_by",
        foreign_keys="InvestigationCase.created_by_id",
        passive_deletes="all",
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="actor", passive_deletes="all"
    )
