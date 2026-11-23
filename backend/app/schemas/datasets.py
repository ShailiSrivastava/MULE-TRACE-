"""Dataset lifecycle request and response schemas."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DatasetStatus = Literal["draft", "ready", "failed", "archived"]


def _validate_metadata(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Metadata must contain JSON-compatible values.") from exc
    if len(encoded) > 65_536:
        raise ValueError("Metadata cannot exceed 64 KiB.")
    return value


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    source: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Dataset name cannot be blank.")
        return normalized

    @field_validator("description", "source")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_metadata(value) or {}


class DatasetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    source: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Dataset name cannot be null.")
        normalized = value.strip()
        if not normalized:
            raise ValueError("Dataset name cannot be blank.")
        return normalized

    @field_validator("description", "source")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any]:
        return _validate_metadata(value)  # type: ignore[return-value]

    @model_validator(mode="after")
    def require_changes(self) -> DatasetUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one dataset field must be supplied.")
        if "metadata" in self.model_fields_set and self.metadata is None:
            raise ValueError("Metadata cannot be null.")
        return self


class DatasetResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    source: str | None
    status: DatasetStatus
    is_synthetic: bool
    metadata: dict[str, Any]
    account_count: int
    transaction_count: int
    created_at: datetime
    updated_at: datetime
