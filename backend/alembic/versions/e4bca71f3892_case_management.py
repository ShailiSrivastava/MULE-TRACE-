"""add investigation case lifecycle, finding links, and retained notes

Revision ID: e4bca71f3892
Revises: c7e4a91d2f60
Create Date: 2026-11-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e4bca71f3892"
down_revision: str | None = "c7e4a91d2f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_document = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    op.add_column(
        "investigation_cases",
        sa.Column(
            "category",
            sa.String(length=80),
            server_default=sa.text("'general'"),
            nullable=False,
        ),
    )
    op.add_column(
        "investigation_cases", sa.Column("assigned_to_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "investigation_cases", sa.Column("archived_by_id", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "investigation_cases", sa.Column("archived_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "investigation_cases",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    with op.batch_alter_table("investigation_cases") as batch_op:
        batch_op.create_check_constraint(
            op.f("ck_investigation_cases_category_not_blank"),
            "length(trim(category)) > 0",
        )
        batch_op.create_foreign_key(
            "fk_investigation_cases_assignee",
            "users",
            ["assigned_to_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_investigation_cases_archiver",
            "users",
            ["archived_by_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_investigation_cases_dataset_assignee",
        "investigation_cases",
        ["dataset_id", "assigned_to_id"],
    )

    op.add_column(
        "case_accounts",
        sa.Column("evidence_snapshot", json_document, nullable=True),
    )
    op.add_column("case_accounts", sa.Column("removed_at", sa.DateTime(timezone=True)))
    op.add_column("case_accounts", sa.Column("removed_by_id", sa.Uuid()))
    with op.batch_alter_table("case_accounts") as batch_op:
        batch_op.create_foreign_key(
            "fk_case_accounts_removed_by_user",
            "users",
            ["removed_by_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "case_findings",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("linked_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "evidence_snapshot",
            json_document,
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_id", "case_id"],
            ["investigation_cases.dataset_id", "investigation_cases.id"],
            name="fk_case_findings_case_dataset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "finding_id"],
            ["detection_findings.dataset_id", "detection_findings.id"],
            name="fk_case_findings_finding_dataset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["linked_by_id"],
            ["users.id"],
            name="fk_case_findings_linked_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["removed_by_id"],
            ["users.id"],
            name="fk_case_findings_removed_by_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "dataset_id", "case_id", "finding_id", name=op.f("pk_case_findings")
        ),
    )
    op.create_index(
        "ix_case_findings_dataset_case_removed",
        "case_findings",
        ["dataset_id", "case_id", "removed_at"],
    )
    op.create_index(
        "ix_case_findings_dataset_finding",
        "case_findings",
        ["dataset_id", "finding_id"],
    )

    op.create_table(
        "case_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
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
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_id", "case_id"],
            ["investigation_cases.dataset_id", "investigation_cases.id"],
            name="fk_case_notes_case_dataset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name="fk_case_notes_author_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_notes")),
        sa.UniqueConstraint(
            "dataset_id", "case_id", "id", name="uq_case_notes_scope_id"
        ),
    )
    op.create_index(
        "ix_case_notes_dataset_case_created",
        "case_notes",
        ["dataset_id", "case_id", "created_at"],
    )

    op.create_table(
        "case_note_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("note_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("edited_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name=op.f("ck_case_note_revisions_revision_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "case_id", "note_id"],
            ["case_notes.dataset_id", "case_notes.case_id", "case_notes.id"],
            name="fk_case_note_revisions_note_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["edited_by_id"],
            ["users.id"],
            name="fk_case_note_revisions_editor_user",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_note_revisions")),
        sa.UniqueConstraint(
            "dataset_id",
            "note_id",
            "revision_number",
            name="uq_case_note_revisions_number",
        ),
    )
    op.create_index(
        "ix_case_note_revisions_dataset_case_note",
        "case_note_revisions",
        ["dataset_id", "case_id", "note_id"],
    )

    op.create_index(
        "ix_audit_logs_entity_created",
        "audit_logs",
        ["entity_type", "entity_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_entity_created", table_name="audit_logs")
    op.drop_index(
        "ix_case_note_revisions_dataset_case_note", table_name="case_note_revisions"
    )
    op.drop_table("case_note_revisions")
    op.drop_index("ix_case_notes_dataset_case_created", table_name="case_notes")
    op.drop_table("case_notes")
    op.drop_index("ix_case_findings_dataset_finding", table_name="case_findings")
    op.drop_index("ix_case_findings_dataset_case_removed", table_name="case_findings")
    op.drop_table("case_findings")
    with op.batch_alter_table("case_accounts") as batch_op:
        batch_op.drop_constraint("fk_case_accounts_removed_by_user", type_="foreignkey")
        batch_op.drop_column("removed_by_id")
        batch_op.drop_column("removed_at")
        batch_op.drop_column("evidence_snapshot")
    op.drop_index(
        "ix_investigation_cases_dataset_assignee", table_name="investigation_cases"
    )
    with op.batch_alter_table("investigation_cases") as batch_op:
        batch_op.drop_constraint("fk_investigation_cases_archiver", type_="foreignkey")
        batch_op.drop_constraint("fk_investigation_cases_assignee", type_="foreignkey")
        batch_op.drop_constraint(
            op.f("ck_investigation_cases_category_not_blank"), type_="check"
        )
        batch_op.drop_column("updated_at")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("archived_by_id")
        batch_op.drop_column("assigned_to_id")
        batch_op.drop_column("category")
