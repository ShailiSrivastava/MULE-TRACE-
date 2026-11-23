"""Account API request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=160)
    account_type: str | None = Field(default=None, max_length=50)
    institution_code: str | None = Field(default=None, max_length=80)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("external_id", "account_type", "institution_code")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank.")
        return normalized

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if len(normalized) != 2 or not normalized.isascii() or not normalized.isalpha():
            raise ValueError("Country code must be a two-letter code.")
        return normalized


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str | None = Field(default=None, min_length=1, max_length=160)
    account_type: str | None = Field(default=None, max_length=50)
    institution_code: str | None = Field(default=None, max_length=80)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    metadata: dict[str, Any] | None = None

    @field_validator("external_id")
    @classmethod
    def validate_external_id(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("External account ID cannot be null.")
        normalized = value.strip()
        if not normalized:
            raise ValueError("External account ID cannot be blank.")
        return normalized

    @field_validator("account_type", "institution_code")
    @classmethod
    def strip_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank.")
        return normalized

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if len(normalized) != 2 or not normalized.isascii() or not normalized.isalpha():
            raise ValueError("Country code must be a two-letter code.")
        return normalized

    @model_validator(mode="after")
    def require_changes(self) -> AccountUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one account field must be supplied.")
        if "metadata" in self.model_fields_set and self.metadata is None:
            raise ValueError("Metadata cannot be null.")
        return self


class AccountResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    external_id: str
    account_type: str | None
    institution_code: str | None
    country_code: str | None
    metadata: dict[str, Any]
    transaction_count: int
    created_at: datetime
    updated_at: datetime
