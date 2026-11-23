"""backfill case account snapshots for pre-Phase 13 associations

Revision ID: e7f192c4a60d
Revises: e4bca71f3892
Create Date: 2026-11-24 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7f192c4a60d"
down_revision: str | None = "e4bca71f3892"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Snapshot safe current account attributes for links made before Phase 13."""

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            UPDATE case_accounts AS ca
            SET evidence_snapshot = jsonb_build_object(
                'account_id', a.id,
                'account_type', a.account_type,
                'institution_code', a.institution_code,
                'country_code', a.country_code,
                'snapshot_at', CURRENT_TIMESTAMP
            )
            FROM accounts AS a
            WHERE ca.dataset_id = a.dataset_id
              AND ca.account_id = a.id
              AND ca.evidence_snapshot IS NULL
            """
        )
    elif op.get_bind().dialect.name == "sqlite":
        op.execute(
            """
            UPDATE case_accounts
            SET evidence_snapshot = (
                SELECT json_object(
                    'account_id', a.id,
                    'account_type', a.account_type,
                    'institution_code', a.institution_code,
                    'country_code', a.country_code,
                    'snapshot_at', CURRENT_TIMESTAMP
                )
                FROM accounts AS a
                WHERE a.dataset_id = case_accounts.dataset_id
                  AND a.id = case_accounts.account_id
            )
            WHERE evidence_snapshot IS NULL
            """
        )


def downgrade() -> None:
    """Keep copied evidence on downgrade; the previous revision removes the column."""
