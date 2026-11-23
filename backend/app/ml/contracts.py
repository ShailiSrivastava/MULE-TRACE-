"""Typed, label-free contracts shared by ML feature and model workflows."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.graph.models import normalize_utc

EntityType = Literal["ACCOUNT", "TRANSACTION"]
PredictionLabel = Literal["ANOMALY", "NORMAL"]
ModelStatus = Literal["TRAINED", "EVALUATED", "ARCHIVED"]
FeatureValue = Decimal | int | None


def _numeric_features(value: Any) -> dict[str, FeatureValue]:
    if not isinstance(value, dict):
        raise TypeError("Features must be a mapping of names to finite numbers.")
    output: dict[str, FeatureValue] = {}
    for raw_name, raw_value in value.items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError("Feature names cannot be blank.")
        if raw_value is None:
            output[name] = None
        elif isinstance(raw_value, bool):
            raise ValueError("Boolean values are not valid numeric features.")
        elif isinstance(raw_value, Decimal):
            if not raw_value.is_finite():
                raise ValueError("Feature values must be finite.")
            output[name] = raw_value
        elif isinstance(raw_value, int):
            output[name] = raw_value
        elif isinstance(raw_value, float):
            if not math.isfinite(raw_value):
                raise ValueError("Feature values must be finite.")
            output[name] = Decimal(str(raw_value))
        else:
            raise ValueError("Feature values must be finite numeric values or None.")
    if len(output) != len(value):
        raise ValueError("Feature names must be unique after normalization.")
    return dict(sorted(output.items()))


class FeatureVector(BaseModel):
    """One feature row with cutoff and evaluation-group metadata.

    ``group_id`` and related entity IDs are metadata, never model inputs. They
    support leakage-safe splitting and controlled Phase 9 association.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: UUID
    entity_type: EntityType
    entity_id: UUID
    feature_schema_version: str = Field(min_length=1, max_length=40)
    as_of: datetime
    features: dict[str, FeatureValue]
    group_id: UUID | None = None
    related_account_ids: tuple[UUID, ...] = ()
    related_transaction_ids: tuple[UUID, ...] = ()

    @field_validator("features", mode="before")
    @classmethod
    def validate_numeric_features(cls, value: Any) -> dict[str, FeatureValue]:
        return _numeric_features(value)

    @field_validator("as_of")
    @classmethod
    def normalize_cutoff(cls, value: datetime) -> datetime:
        return normalize_utc(value, field_name="feature cutoff")

    @field_validator("related_account_ids", "related_transaction_ids")
    @classmethod
    def stable_references(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(value), key=str))

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(self.features)


class AnomalyPrediction(BaseModel):
    """Explainable model output; scores are explicitly not probabilities."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: UUID
    entity_type: EntityType
    entity_id: UUID
    model_name: str
    model_version: str
    feature_schema_version: str
    score_type: Literal["ANOMALY_SCORE"] = "ANOMALY_SCORE"
    raw_anomaly_score: float = Field(ge=0, allow_inf_nan=False)
    normalized_anomaly_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    prediction_label: PredictionLabel
    cluster_id: int | None = None
    model_parameters: dict[str, Any]
    feature_values: dict[str, FeatureValue]
    as_of: datetime
    analysis_timestamp: datetime
    explanations: tuple[str, ...]
    related_account_ids: tuple[UUID, ...] = ()
    related_transaction_ids: tuple[UUID, ...] = ()

    @field_validator("feature_values", mode="before")
    @classmethod
    def validate_numeric_features(cls, value: Any) -> dict[str, FeatureValue]:
        return _numeric_features(value)

    @field_validator("as_of", "analysis_timestamp")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        return normalize_utc(value, field_name="prediction timestamp")

    @field_validator("related_account_ids", "related_transaction_ids")
    @classmethod
    def stable_references(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(value), key=str))


class ModelRegistryMetadata(BaseModel):
    """Reproducibility metadata persisted without model artifacts or raw rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    model_version: str = Field(min_length=1, max_length=40)
    feature_schema_version: str = Field(min_length=1, max_length=40)
    training_dataset_id: UUID
    training_timestamp: datetime
    training_sample_count: int = Field(ge=2)
    entity_type: EntityType
    feature_names: tuple[str, ...]
    model_parameters: dict[str, Any]
    preprocessing_config: dict[str, Any]
    evaluation_metrics: dict[str, Any] | None = None
    random_seed: int = Field(ge=0)
    status: ModelStatus = "TRAINED"

    @field_validator("training_timestamp")
    @classmethod
    def normalize_training_timestamp(cls, value: datetime) -> datetime:
        return normalize_utc(value, field_name="training_timestamp")

    @field_validator("feature_names")
    @classmethod
    def validate_feature_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("Registry feature names must be nonempty and unique.")
        return tuple(sorted(value))
