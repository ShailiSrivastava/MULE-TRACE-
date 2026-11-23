"""CSV import tracking and row-level result schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ImportType = Literal["accounts", "transactions"]
ImportStatus = Literal["pending", "completed", "failed"]


class CsvRowError(BaseModel):
    row: int = Field(ge=0)
    code: str
    message: str


class ImportJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    import_type: ImportType
    original_filename: str
    status: ImportStatus
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    skipped_rows: int
    duplicate_rows: int
    error_summary: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None


class ImportResult(ImportJobResponse):
    row_errors: list[CsvRowError] = Field(default_factory=list)
