"""Validated, jurisdiction-neutral thresholds for individual detectors."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DetectorSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    max_findings: int = Field(default=100, ge=1, le=1_000)
    max_windows_examined: int = Field(default=100_000, ge=1, le=1_000_000)


def _currency_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise ValueError("Currency keys must be three-letter codes.")
    return code


def _currency_amounts(value: Any) -> dict[str, Decimal]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Currency thresholds must be a mapping.")  # noqa: TRY004
    result: dict[str, Decimal] = {}
    for raw_code, raw_amount in value.items():
        code = _currency_code(str(raw_code))
        if code in result:
            raise ValueError(
                "Currency threshold keys cannot repeat after normalization."
            )
        if isinstance(raw_amount, bool):
            raise ValueError("Currency thresholds must be finite decimals.")  # noqa: TRY004
        try:
            amount = (
                raw_amount
                if isinstance(raw_amount, Decimal)
                else Decimal(str(raw_amount))
            )
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("Currency thresholds must be finite decimals.") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError("Currency thresholds must be finite and non-negative.")
        result[code] = amount
    return dict(sorted(result.items()))


class RapidTransfersConfig(DetectorSettings):
    minimum_transaction_count: int = Field(default=3, ge=2, le=20)
    maximum_elapsed_seconds: int = Field(default=3_600, ge=1, le=604_800)
    minimum_distinct_accounts: int = Field(default=3, ge=2, le=20)
    maximum_path_length: int = Field(default=6, ge=2, le=8)
    minimum_amount_by_currency: dict[str, Decimal] = Field(default_factory=dict)
    max_edge_expansions: int = Field(default=50_000, ge=1, le=500_000)

    @field_validator("minimum_amount_by_currency", mode="before")
    @classmethod
    def normalize_amount_thresholds(cls, value: Any) -> dict[str, Decimal]:
        return _currency_amounts(value)

    @model_validator(mode="after")
    def path_limits_fit_minimums(self) -> RapidTransfersConfig:
        if self.minimum_transaction_count > self.maximum_path_length:
            raise ValueError(
                "minimum_transaction_count cannot exceed maximum_path_length."
            )
        if self.minimum_distinct_accounts > self.maximum_path_length + 1:
            raise ValueError(
                "minimum_distinct_accounts cannot exceed maximum_path_length + 1."
            )
        return self


class FanInConfig(DetectorSettings):
    window_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    minimum_unique_senders: int = Field(default=5, ge=2, le=10_000)
    minimum_incoming_transactions: int = Field(default=5, ge=2, le=100_000)
    minimum_total_amount_by_currency: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("minimum_total_amount_by_currency", mode="before")
    @classmethod
    def normalize_amount_thresholds(cls, value: Any) -> dict[str, Decimal]:
        return _currency_amounts(value)


class FanOutConfig(DetectorSettings):
    window_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    minimum_unique_receivers: int = Field(default=5, ge=2, le=10_000)
    minimum_outgoing_transactions: int = Field(default=5, ge=2, le=100_000)
    minimum_total_amount_by_currency: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("minimum_total_amount_by_currency", mode="before")
    @classmethod
    def normalize_amount_thresholds(cls, value: Any) -> dict[str, Decimal]:
        return _currency_amounts(value)


class CircularMovementConfig(DetectorSettings):
    time_window_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    minimum_cycle_length: int = Field(default=3, ge=2, le=8)
    maximum_cycle_length: int = Field(default=6, ge=2, le=8)
    maximum_cycles: int = Field(default=100, ge=1, le=1_000)
    maximum_edge_expansions: int = Field(default=100_000, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def valid_cycle_bounds(self) -> CircularMovementConfig:
        if self.minimum_cycle_length > self.maximum_cycle_length:
            raise ValueError("minimum_cycle_length cannot exceed maximum_cycle_length.")
        return self


class MultiHopConfig(DetectorSettings):
    time_window_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    maximum_hops: int = Field(default=4, ge=2, le=8)
    maximum_paths: int = Field(default=100, ge=1, le=100)
    maximum_pairs_examined: int = Field(default=10_000, ge=1, le=100_000)
    maximum_expansions_per_pair: int = Field(default=1_000, ge=1, le=100_000)
    maximum_total_expansions: int = Field(default=100_000, ge=1, le=1_000_000)
    minimum_amount_by_currency: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("minimum_amount_by_currency", mode="before")
    @classmethod
    def normalize_amount_thresholds(cls, value: Any) -> dict[str, Decimal]:
        return _currency_amounts(value)


class UnusualActivityConfig(DetectorSettings):
    activity_window_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    baseline_periods: int = Field(default=14, ge=2, le=90)
    minimum_baseline_periods: int = Field(default=7, ge=2, le=90)
    minimum_baseline_transactions: int = Field(default=5, ge=1, le=100_000)
    minimum_observed_transactions: int = Field(default=3, ge=1, le=100_000)
    frequency_standard_deviation_multiplier: Decimal = Field(
        default=Decimal("3.0"), ge=0
    )
    minimum_amount_baseline_transactions: int = Field(default=5, ge=2, le=100_000)
    amount_mad_multiplier: Decimal = Field(default=Decimal("3.5"), gt=0)

    @model_validator(mode="after")
    def baseline_requirements_fit_horizon(self) -> UnusualActivityConfig:
        if self.minimum_baseline_periods > self.baseline_periods:
            raise ValueError("minimum_baseline_periods cannot exceed baseline_periods.")
        return self


class StructuringBand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_amount: Decimal = Field(ge=0)
    maximum_amount: Decimal = Field(gt=0)

    @field_validator("minimum_amount", "maximum_amount", mode="before")
    @classmethod
    def reject_float_amounts(cls, value: Any) -> Any:
        if isinstance(value, bool | float):
            raise ValueError("Structuring band amounts must be finite decimals.")  # noqa: TRY004
        return value

    @model_validator(mode="after")
    def ordered_band(self) -> StructuringBand:
        if self.minimum_amount > self.maximum_amount:
            raise ValueError("Structuring band minimum cannot exceed maximum.")
        return self


class StructuringConfig(DetectorSettings):
    window_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    minimum_transaction_count: int = Field(default=3, ge=2, le=100_000)
    minimum_active_days: int = Field(default=1, ge=1, le=30)
    threshold_bands_by_currency: dict[str, tuple[StructuringBand, ...]] = Field(
        default_factory=dict
    )

    @field_validator("threshold_bands_by_currency", mode="before")
    @classmethod
    def normalize_bands(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("threshold_bands_by_currency must be a mapping.")  # noqa: TRY004
        result: dict[str, Any] = {}
        for raw_code, raw_bands in value.items():
            code = _currency_code(str(raw_code))
            if code in result:
                raise ValueError(
                    "Currency band keys cannot repeat after normalization."
                )
            bands = [
                band
                if isinstance(band, StructuringBand)
                else StructuringBand.model_validate(band)
                for band in raw_bands
            ]
            bands.sort(key=lambda band: (band.minimum_amount, band.maximum_amount))
            for previous, current in pairwise(bands):
                if previous.maximum_amount >= current.minimum_amount:
                    raise ValueError("Structuring bands for a currency cannot overlap.")
            result[code] = tuple(bands)
        return dict(sorted(result.items()))


class DetectionConfig(BaseModel):
    """Complete immutable detector configuration; amount rules are per currency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rapid_transfers: RapidTransfersConfig = Field(default_factory=RapidTransfersConfig)
    fan_in: FanInConfig = Field(default_factory=FanInConfig)
    fan_out: FanOutConfig = Field(default_factory=FanOutConfig)
    circular_movement: CircularMovementConfig = Field(
        default_factory=CircularMovementConfig
    )
    multi_hop: MultiHopConfig = Field(default_factory=MultiHopConfig)
    unusual_activity: UnusualActivityConfig = Field(
        default_factory=UnusualActivityConfig
    )
    structuring: StructuringConfig = Field(default_factory=StructuringConfig)
