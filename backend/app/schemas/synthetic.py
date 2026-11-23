"""Synthetic dataset generation request and response schemas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SyntheticPattern = Literal[
    "rapid_successive",
    "fan_in",
    "fan_out",
    "circular",
    "multi_hop",
    "unusual_amount",
    "unusual_frequency",
]

DEFAULT_PATTERNS: tuple[SyntheticPattern, ...] = (
    "rapid_successive",
    "fan_in",
    "fan_out",
    "circular",
    "multi_hop",
    "unusual_amount",
    "unusual_frequency",
)

PATTERN_TRANSACTION_COUNTS = {
    "rapid_successive": 3,
    "fan_in": 4,
    "fan_out": 4,
    "circular": 3,
    "multi_hop": 4,
    "unusual_amount": 1,
    "unusual_frequency": 3,
}


def _now_utc() -> datetime:
    return datetime.now(UTC)


class SyntheticGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_count: int = Field(default=100, ge=2, le=2_000)
    transaction_count: int = Field(default=1_000, ge=1, le=20_000)
    start_at: datetime = Field(default_factory=lambda: _now_utc() - timedelta(days=30))
    end_at: datetime = Field(default_factory=_now_utc)
    currencies: list[str] = Field(
        default_factory=lambda: ["USD", "EUR", "GBP"], min_length=1, max_length=10
    )
    seed: int = Field(default=42, ge=0, le=4_294_967_295)
    patterns: list[SyntheticPattern] = Field(
        default_factory=lambda: list(DEFAULT_PATTERNS), max_length=7
    )

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone offset.")
        return value.astimezone(UTC)

    @field_validator("currencies")
    @classmethod
    def normalize_currencies(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            code = value.strip().upper()
            if len(code) != 3 or not code.isascii() or not code.isalpha():
                raise ValueError("Each currency must be a three-letter code.")
            if code not in normalized:
                normalized.append(code)
        if not normalized:
            raise ValueError("At least one currency is required.")
        return normalized

    @field_validator("patterns")
    @classmethod
    def patterns_must_be_unique(
        cls, values: list[SyntheticPattern]
    ) -> list[SyntheticPattern]:
        if len(values) != len(set(values)):
            raise ValueError("Synthetic patterns cannot be repeated.")
        return values

    @model_validator(mode="after")
    def validate_generation_bounds(self) -> SyntheticGenerationRequest:
        if self.start_at >= self.end_at:
            raise ValueError("end_at must be later than start_at.")
        if self.patterns and self.end_at - self.start_at < timedelta(minutes=30):
            raise ValueError("Pattern generation requires at least a 30-minute range.")
        required_accounts = 2
        for pattern in self.patterns:
            if pattern in {"fan_in", "fan_out", "multi_hop"}:
                required_accounts = max(required_accounts, 5)
            elif pattern == "circular":
                required_accounts = max(required_accounts, 3)
            elif pattern == "unusual_frequency":
                required_accounts = max(required_accounts, 4)
        if self.account_count < required_accounts:
            raise ValueError(
                f"Selected patterns require at least {required_accounts} accounts."
            )
        minimum_transactions = sum(
            PATTERN_TRANSACTION_COUNTS[pattern] for pattern in self.patterns
        )
        if self.transaction_count < minimum_transactions:
            raise ValueError(
                "transaction_count is too small for the selected synthetic patterns."
            )
        return self


class SyntheticGenerationResponse(BaseModel):
    dataset_id: UUID
    seed: int
    account_count: int
    transaction_count: int
    normal_transaction_count: int
    ground_truth_label_count: int
    patterns: list[SyntheticPattern]
    is_synthetic: bool
