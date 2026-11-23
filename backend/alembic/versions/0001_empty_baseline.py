"""Establish the empty MuleTrace schema migration baseline.

Revision ID: 0001_empty_baseline
Revises:
Create Date: 2026-11-23
"""

from collections.abc import Sequence

revision: str = "0001_empty_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the migration version table; business schema comes in Phase 3."""


def downgrade() -> None:
    """No application tables are defined by this baseline."""
