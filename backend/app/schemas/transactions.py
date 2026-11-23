"""Transaction API request and response schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TransactionSortField = Literal["occurred_at", "created_at", "amount", "currency"]
SortDirection = Literal["asc", "desc"]


def _normalize_currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError("Currency must be a three-letter code.")
    return normalized


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone offset.")
    return value.astimezone(UTC)


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_account_id: UUID
    receiver_account_id: UUID
    external_transaction_id: str | None = Field(default=None, max_length=160)
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    currency: str = Field(min_length=3, max_length=3)
    transaction_type: str | None = Field(default=None, max_length=60)
    channel: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, max_length=40)
    occurred_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return _normalize_currency(value)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        return _normalize_timestamp(value)

    @field_validator("external_transaction_id", "transaction_type", "channel", "status")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank.")
        return normalized

    @model_validator(mode="after")
    def accounts_must_differ(self) -> TransactionCreate:
        if self.sender_account_id == self.receiver_account_id:
            raise ValueError("Sender and receiver accounts must be different.")
        return self


class TransactionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_transaction_id: str | None = Field(default=None, max_length=160)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=6)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    transaction_type: str | None = Field(default=None, max_length=60)
    channel: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, max_length=40)
    occurred_at: datetime | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("amount", "currency", "occurred_at")
    @classmethod
    def required_when_supplied(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Field cannot be null.")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return None if value is None else _normalize_currency(value)

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _normalize_timestamp(value)

    @field_validator("external_transaction_id", "transaction_type", "channel", "status")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank.")
        return normalized

    @model_validator(mode="after")
    def require_changes(self) -> TransactionUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one transaction field must be supplied.")
        if "metadata" in self.model_fields_set and self.metadata is None:
            raise ValueError("Metadata cannot be null.")
        return self


class TransactionResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    sender_account_id: UUID
    receiver_account_id: UUID
    external_transaction_id: str | None
    amount: Decimal
    currency: str
    transaction_type: str | None
    channel: str | None
    status: str | None
    occurred_at: datetime
    metadata: dict[str, Any]
    created_at: datetime
