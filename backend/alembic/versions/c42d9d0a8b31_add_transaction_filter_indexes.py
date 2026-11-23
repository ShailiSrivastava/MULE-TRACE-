"""add indexes for transaction amount and currency filters

Revision ID: c42d9d0a8b31
Revises: 899fa61457b5
Create Date: 2026-11-23 15:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c42d9d0a8b31"
down_revision: str | None = "899fa61457b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_transactions_dataset_currency_occurred",
        "transactions",
        ["dataset_id", "currency", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_transactions_dataset_amount",
        "transactions",
        ["dataset_id", "amount"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_dataset_amount", table_name="transactions")
    op.drop_index(
        "ix_transactions_dataset_currency_occurred", table_name="transactions"
    )
