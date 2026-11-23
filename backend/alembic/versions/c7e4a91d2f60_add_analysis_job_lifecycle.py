"""add asynchronous analysis job lifecycle metadata

Revision ID: c7e4a91d2f60
Revises: b18f3a9d2c74
Create Date: 2026-11-23 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e4a91d2f60"
down_revision: str | None = "b18f3a9d2c74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_jobs",
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("analysis_jobs", sa.Column("current_stage", sa.String(length=80)))
    op.add_column(
        "analysis_jobs",
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("analysis_jobs", sa.Column("task_id", sa.String(length=80)))
    op.add_column(
        "analysis_jobs", sa.Column("idempotency_key", sa.String(length=128))
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "analysis_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE analysis_jobs SET updated_at = CURRENT_TIMESTAMP "
        "WHERE updated_at IS NULL"
    )
    if op.get_bind().dialect.name != "sqlite":
        op.alter_column(
            "analysis_jobs",
            "updated_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        )
        op.create_check_constraint(
            "ck_analysis_jobs_progress_percent_range",
            "analysis_jobs",
            "progress_percent >= 0 AND progress_percent <= 100",
        )
        op.create_check_constraint(
            "ck_analysis_jobs_retry_count_nonnegative",
            "analysis_jobs",
            "retry_count >= 0",
        )
        op.create_unique_constraint(
            "uq_analysis_jobs_owner_idempotency",
            "analysis_jobs",
            ["dataset_id", "created_by_id", "idempotency_key"],
        )
        op.create_unique_constraint(
            "uq_analysis_jobs_task_id", "analysis_jobs", ["task_id"]
        )
    else:
        # SQLite cannot add constraints in-place. Avoid batch table rebuilds here:
        # dropping analysis_jobs with foreign keys enabled cascades existing findings.
        op.create_index(
            "uq_analysis_jobs_owner_idempotency",
            "analysis_jobs",
            ["dataset_id", "created_by_id", "idempotency_key"],
            unique=True,
        )
        op.create_index(
            "uq_analysis_jobs_task_id", "analysis_jobs", ["task_id"], unique=True
        )
    op.create_index(
        "ix_analysis_jobs_status_heartbeat",
        "analysis_jobs",
        ["status", "heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_jobs_status_heartbeat", table_name="analysis_jobs")
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index(
            "uq_analysis_jobs_task_id", table_name="analysis_jobs"
        )
        op.drop_index(
            "uq_analysis_jobs_owner_idempotency", table_name="analysis_jobs"
        )
    else:
        op.drop_constraint(
            "uq_analysis_jobs_task_id", "analysis_jobs", type_="unique"
        )
        op.drop_constraint(
            "uq_analysis_jobs_owner_idempotency",
            "analysis_jobs",
            type_="unique",
        )
        op.drop_constraint(
            "ck_analysis_jobs_retry_count_nonnegative",
            "analysis_jobs",
            type_="check",
        )
        op.drop_constraint(
            "ck_analysis_jobs_progress_percent_range",
            "analysis_jobs",
            type_="check",
        )
    for column in (
        "updated_at",
        "heartbeat_at",
        "cancel_requested_at",
        "idempotency_key",
        "task_id",
        "retry_count",
        "current_stage",
        "progress_percent",
    ):
        op.drop_column("analysis_jobs", column)
