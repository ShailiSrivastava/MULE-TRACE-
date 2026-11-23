"""add durable ML model-version metadata

Revision ID: b18f3a9d2c74
Revises: d41f6f8b9c20
Create Date: 2026-11-23 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b18f3a9d2c74"
down_revision: str | None = "d41f6f8b9c20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_document = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    op.create_table(
        "ml_model_registry",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.String(length=80), nullable=False),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.Column("feature_schema_version", sa.String(length=40), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("training_dataset_id", sa.Uuid(), nullable=True),
        sa.Column("training_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("training_sample_count", sa.Integer(), nullable=False),
        sa.Column("feature_names", json_document, nullable=False),
        sa.Column("model_parameters", json_document, nullable=False),
        sa.Column("preprocessing_config", json_document, nullable=False),
        sa.Column("evaluation_metrics", json_document, nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('ACCOUNT', 'TRANSACTION')",
            name=op.f("ck_ml_model_registry_entity_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('TRAINED', 'EVALUATED', 'ARCHIVED')",
            name=op.f("ck_ml_model_registry_status_valid"),
        ),
        sa.CheckConstraint(
            "training_sample_count >= 2",
            name=op.f("ck_ml_model_registry_training_sample_count_minimum"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_ml_model_registry_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["training_dataset_id"],
            ["datasets.id"],
            name="fk_ml_model_registry_dataset",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_model_registry")),
        sa.UniqueConstraint(
            "model_name", "model_version", name="uq_ml_model_name_version"
        ),
    )
    op.create_index(
        "ix_ml_model_registry_dataset_status",
        "ml_model_registry",
        ["training_dataset_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_ml_model_registry_created_at",
        "ml_model_registry",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ml_model_registry_created_at", table_name="ml_model_registry")
    op.drop_index(
        "ix_ml_model_registry_dataset_status", table_name="ml_model_registry"
    )
    op.drop_table("ml_model_registry")
