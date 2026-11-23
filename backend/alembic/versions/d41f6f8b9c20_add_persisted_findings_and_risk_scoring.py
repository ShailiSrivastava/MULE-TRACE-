"""add persisted findings, lifecycle history, and versioned risk scores

Revision ID: d41f6f8b9c20
Revises: 7e91c4ab2d60
Create Date: 2026-11-23 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d41f6f8b9c20"
down_revision: str | None = "7e91c4ab2d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_document = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    op.create_table(
        "detection_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("detector_name", sa.String(length=80), nullable=False),
        sa.Column("detector_version", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("deduplication_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'NEW'"),
            nullable=False,
        ),
        sa.Column("assigned_to_id", sa.Uuid(), nullable=True),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parameters", json_document, nullable=False),
        sa.Column("evidence", json_document, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'low', 'medium', 'high', 'critical')",
            name=op.f("ck_detection_findings_severity_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('NEW', 'REVIEWING', 'RESOLVED', 'DISMISSED')",
            name=op.f("ck_detection_findings_status_valid"),
        ),
        sa.CheckConstraint(
            "length(deduplication_key) = 64",
            name=op.f("ck_detection_findings_deduplication_key_sha256_length"),
        ),
        sa.CheckConstraint(
            "last_detected_at >= first_detected_at",
            name=op.f("ck_detection_findings_last_detected_after_first_detected"),
        ),
        sa.CheckConstraint(
            "(event_window_start IS NULL AND event_window_end IS NULL) OR "
            "(event_window_start IS NOT NULL AND event_window_end IS NOT NULL "
            "AND event_window_end >= event_window_start)",
            name=op.f("ck_detection_findings_event_window_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_id"],
            ["users.id"],
            name="fk_detection_findings_assignee",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_detection_findings_dataset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_detection_findings")),
        sa.UniqueConstraint(
            "dataset_id", "id", name="uq_detection_findings_dataset_id_id"
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "deduplication_key",
            name="uq_detection_findings_dataset_dedup",
        ),
    )
    op.create_index(
        "ix_detection_findings_dataset_status_last",
        "detection_findings",
        ["dataset_id", "status", "last_detected_at"],
        unique=False,
    )
    op.create_index(
        "ix_detection_findings_dataset_severity",
        "detection_findings",
        ["dataset_id", "severity"],
        unique=False,
    )
    op.create_index(
        "ix_detection_findings_dataset_category",
        "detection_findings",
        ["dataset_id", "category"],
        unique=False,
    )
    op.create_index(
        "ix_detection_findings_dataset_assignee",
        "detection_findings",
        ["dataset_id", "assigned_to_id"],
        unique=False,
    )

    op.create_table(
        "finding_accounts",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relationship_role",
            sa.String(length=20),
            server_default=sa.text("'participant'"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relationship_role IN ('participant', 'center', 'source', 'destination', 'intermediary')",
            name=op.f("ck_finding_accounts_relationship_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "account_id"],
            ["accounts.dataset_id", "accounts.id"],
            name="fk_finding_accounts_account_dataset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            name="fk_finding_accounts_finding_dataset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_id", "finding_id", "account_id", name=op.f("pk_finding_accounts")
        ),
    )
    op.create_index(
        "ix_finding_accounts_dataset_account",
        "finding_accounts",
        ["dataset_id", "account_id"],
        unique=False,
    )

    op.create_table(
        "finding_transactions",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column(
            "evidence_role",
            sa.String(length=80),
            server_default=sa.text("'supporting_evidence'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            name="fk_finding_transactions_finding_dataset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "transaction_id"],
            ["transactions.dataset_id", "transactions.id"],
            name="fk_finding_transactions_transaction_dataset",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_id", "finding_id", "transaction_id",
            name=op.f("pk_finding_transactions"),
        ),
    )
    op.create_index(
        "ix_finding_transactions_dataset_transaction",
        "finding_transactions",
        ["dataset_id", "transaction_id"],
        unique=False,
    )

    op.create_table(
        "finding_observations",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("parameters", json_document, nullable=False),
        sa.Column("evidence", json_document, nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id", "analysis_job_id"],
            ["analysis_jobs.dataset_id", "analysis_jobs.id"],
            name="fk_finding_observations_analysis_job_dataset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            name="fk_finding_observations_finding_dataset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_id", "finding_id", "analysis_job_id",
            name=op.f("pk_finding_observations"),
        ),
    )
    op.create_index(
        "ix_finding_observations_dataset_job",
        "finding_observations",
        ["dataset_id", "analysis_job_id"],
        unique=False,
    )

    op.create_table(
        "finding_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "to_status IN ('NEW', 'REVIEWING', 'RESOLVED', 'DISMISSED')",
            name=op.f("ck_finding_status_history_to_status_valid"),
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('NEW', 'REVIEWING', 'RESOLVED', 'DISMISSED')",
            name=op.f("ck_finding_status_history_from_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name="fk_finding_status_history_actor",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            name="fk_finding_status_history_finding_dataset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_status_history")),
    )
    op.create_index(
        "ix_finding_status_history_dataset_finding_time",
        "finding_status_history",
        ["dataset_id", "finding_id", "changed_at"],
        unique=False,
    )

    with op.batch_alter_table("risk_assessments") as batch_op:
        batch_op.alter_column(
            "account_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )
        batch_op.add_column(sa.Column("finding_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "scoring_model_version",
                sa.String(length=40),
                server_default=sa.text("'legacy'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "score_components",
                json_document,
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )
        batch_op.drop_constraint("uq_risk_assessments_job_account", type_="unique")
        batch_op.create_unique_constraint(
            "uq_risk_assessments_job_account_version",
            ["analysis_job_id", "account_id", "scoring_model_version"],
        )
        batch_op.create_unique_constraint(
            "uq_risk_assessments_job_finding_version",
            ["analysis_job_id", "finding_id", "scoring_model_version"],
        )
        batch_op.create_check_constraint(
            op.f("ck_risk_assessments_assessment_scope_exactly_one"),
            "(account_id IS NOT NULL AND finding_id IS NULL) OR "
            "(account_id IS NULL AND finding_id IS NOT NULL)",
        )
        batch_op.create_foreign_key(
            "fk_risk_assessments_finding_dataset",
            "detection_findings",
            ["dataset_id", "finding_id"],
            ["dataset_id", "id"],
            ondelete="CASCADE",
        )
    # SQLite rebuilds this table for batch operations. Keep the temporary
    # defaults through the copy so existing assessments receive legacy values.
    with op.batch_alter_table("risk_assessments") as batch_op:
        batch_op.alter_column(
            "scoring_model_version",
            existing_type=sa.String(length=40),
            server_default=None,
        )
        batch_op.alter_column(
            "score_components",
            existing_type=json_document,
            server_default=None,
        )
    op.create_index(
        "ix_risk_assessments_dataset_finding",
        "risk_assessments",
        ["dataset_id", "finding_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_risk_assessments_dataset_finding", table_name="risk_assessments")
    with op.batch_alter_table("risk_assessments") as batch_op:
        batch_op.drop_constraint("fk_risk_assessments_finding_dataset", type_="foreignkey")
        batch_op.drop_constraint(
            op.f("ck_risk_assessments_assessment_scope_exactly_one"), type_="check"
        )
        batch_op.drop_constraint(
            "uq_risk_assessments_job_account_version", type_="unique"
        )
        batch_op.drop_constraint(
            "uq_risk_assessments_job_finding_version", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_risk_assessments_job_account", ["analysis_job_id", "account_id"]
        )
        batch_op.drop_column("score_components")
        batch_op.drop_column("scoring_model_version")
        batch_op.drop_column("finding_id")
        batch_op.alter_column(
            "account_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )

    op.drop_index(
        "ix_finding_status_history_dataset_finding_time",
        table_name="finding_status_history",
    )
    op.drop_table("finding_status_history")
    op.drop_index("ix_finding_observations_dataset_job", table_name="finding_observations")
    op.drop_table("finding_observations")
    op.drop_index(
        "ix_finding_transactions_dataset_transaction", table_name="finding_transactions"
    )
    op.drop_table("finding_transactions")
    op.drop_index("ix_finding_accounts_dataset_account", table_name="finding_accounts")
    op.drop_table("finding_accounts")
    op.drop_index(
        "ix_detection_findings_dataset_assignee", table_name="detection_findings"
    )
    op.drop_index(
        "ix_detection_findings_dataset_category", table_name="detection_findings"
    )
    op.drop_index(
        "ix_detection_findings_dataset_severity", table_name="detection_findings"
    )
    op.drop_index(
        "ix_detection_findings_dataset_status_last", table_name="detection_findings"
    )
    op.drop_table("detection_findings")
