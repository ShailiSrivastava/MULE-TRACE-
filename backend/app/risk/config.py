"""Validated, adjustable risk contribution weights and illustrative bands."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_DETECTOR_WEIGHTS = {
    "rapid_transfers": Decimal("0.90"),
    "fan_in": Decimal("0.75"),
    "fan_out": Decimal("0.75"),
    "circular_movement": Decimal("0.95"),
    "multi_hop": Decimal("0.65"),
    "unusual_activity": Decimal("0.65"),
    "structuring": Decimal("0.70"),
}

DEFAULT_SEVERITY_CONTRIBUTIONS = {
    "info": Decimal("0.05"),
    "low": Decimal("0.20"),
    "medium": Decimal("0.40"),
    "high": Decimal("0.70"),
    "critical": Decimal("0.90"),
}


def _weight_map(value: Any) -> dict[str, Decimal]:
    if not isinstance(value, dict):
        raise ValueError("Scoring weights must be a mapping.")  # noqa: TRY004
    weights: dict[str, Decimal] = {}
    for raw_key, raw_weight in value.items():
        key = str(raw_key).strip().lower()
        if not key:
            raise ValueError("Scoring weight keys cannot be blank.")
        if isinstance(raw_weight, bool | float):
            raise ValueError("Scoring weights must be finite decimal values.")  # noqa: TRY004
        try:
            weight = (
                raw_weight
                if isinstance(raw_weight, Decimal)
                else Decimal(str(raw_weight))
            )
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Scoring weights must be finite decimal values.") from exc
        if not weight.is_finite() or not Decimal(0) <= weight <= Decimal(1):
            raise ValueError("Scoring weights must be finite values between 0 and 1.")
        if key in weights:
            raise ValueError("Scoring weight keys cannot repeat after normalization.")
        weights[key] = weight
    return dict(sorted(weights.items()))


class RiskScoringConfig(BaseModel):
    """Immutable scoring parameters; all weights and band cutoffs are adjustable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str = Field(default="1.0", min_length=1, max_length=40)
    detector_weights: dict[str, Decimal] = Field(
        default_factory=lambda: dict(DEFAULT_DETECTOR_WEIGHTS)
    )
    category_weights: dict[str, Decimal] = Field(default_factory=dict)
    severity_contributions: dict[str, Decimal] = Field(
        default_factory=lambda: dict(DEFAULT_SEVERITY_CONTRIBUTIONS)
    )
    default_detector_weight: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    default_category_weight: Decimal = Field(default=Decimal("1.00"), ge=0, le=1)
    low_upper_bound: Decimal = Field(default=Decimal("0.25"), gt=0, lt=1)
    medium_upper_bound: Decimal = Field(default=Decimal("0.50"), gt=0, lt=1)
    high_upper_bound: Decimal = Field(default=Decimal("0.75"), gt=0, lt=1)

    @field_validator(
        "detector_weights", "category_weights", "severity_contributions", mode="before"
    )
    @classmethod
    def validate_weight_maps(cls, value: Any) -> dict[str, Decimal]:
        return _weight_map(value)

    @field_validator(
        "default_detector_weight",
        "default_category_weight",
        "low_upper_bound",
        "medium_upper_bound",
        "high_upper_bound",
        mode="before",
    )
    @classmethod
    def reject_float_scalars(cls, value: Any) -> Any:
        if isinstance(value, bool | float):
            raise ValueError("Scoring values must be finite decimals.")  # noqa: TRY004
        return value

    @model_validator(mode="after")
    def validate_band_order(self) -> RiskScoringConfig:
        valid_severities = {"info", "low", "medium", "high", "critical"}
        if not set(self.severity_contributions) <= valid_severities:
            raise ValueError("Severity contribution keys must be valid severity names.")
        if not valid_severities <= set(self.severity_contributions):
            raise ValueError("A contribution must be configured for every severity.")
        if not (
            Decimal(0) < self.low_upper_bound
            < self.medium_upper_bound
            < self.high_upper_bound
            < Decimal(1)
        ):
            raise ValueError(
                "Risk band cutoffs must be strictly increasing inside the interval (0, 1)."
            )
        return self
