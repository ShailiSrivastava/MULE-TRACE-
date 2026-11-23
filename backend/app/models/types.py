"""Database types shared by the model modules."""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB


def json_document_type():
    """Use PostgreSQL JSONB with a portable JSON fallback for SQLite tests."""

    return JSON().with_variant(JSONB(), "postgresql")
