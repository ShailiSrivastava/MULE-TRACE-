"""add dataset-scoped CSV import tracking

Revision ID: 7e91c4ab2d60
Revises: c42d9d0a8b31
Create Date: 2026-11-23 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7e91c4ab2d60"
down_revision: str | None = "c42d9d0a8b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("import_type", sa.String(length=20), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "total_rows", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "accepted_rows", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "rejected_rows", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "skipped_rows", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "duplicate_rows", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "error_summary",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "accepted_rows >= 0 AND duplicate_rows >= 0 AND rejected_rows >= 0 "
            "AND skipped_rows >= 0 AND total_rows >= 0",
            name=op.f("ck_import_jobs_counts_nonnegative"),
        ),
        sa.CheckConstraint(
            "import_type IN ('accounts', 'transactions')",
            name=op.f("ck_import_jobs_import_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name=op.f("ck_import_jobs_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_import_jobs_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_import_jobs_dataset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_jobs")),
    )
    op.create_index(
        "ix_import_jobs_dataset_created",
        "import_jobs",
        ["dataset_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_import_jobs_status", "import_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_import_jobs_status", table_name="import_jobs")
    op.drop_index("ix_import_jobs_dataset_created", table_name="import_jobs")
    op.drop_table("import_jobs")
