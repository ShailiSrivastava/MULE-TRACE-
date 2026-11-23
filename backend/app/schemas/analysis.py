"""Validated analysis submission and safe job response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.detection.config import DetectionConfig
from app.graph.models import normalize_utc
from app.ml.clustering import KMeansConfig
from app.ml.isolation_forest import IsolationForestConfig
from app.ml.local_outlier_factor import LocalOutlierFactorConfig
from app.risk.config import RiskScoringConfig

AnalysisJobState = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
AnalysisEntityType = Literal["ACCOUNT", "TRANSACTION"]
AnalysisAlgorithm = Literal["isolation_forest", "local_outlier_factor", "kmeans"]


class MLAnalysisConfig(BaseModel):
    """Bounded model choices for one self-contained worker execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    entity_types: list[AnalysisEntityType] = Field(
        default_factory=lambda: ["ACCOUNT", "TRANSACTION"], min_length=1, max_length=2
    )
    algorithms: list[AnalysisAlgorithm] = Field(
        default_factory=lambda: ["isolation_forest"], min_length=1, max_length=3
    )
    isolation_forest: IsolationForestConfig = Field(
        default_factory=IsolationForestConfig
    )
    local_outlier_factor: LocalOutlierFactorConfig = Field(
        default_factory=LocalOutlierFactorConfig
    )
    kmeans: KMeansConfig = Field(default_factory=KMeansConfig)

    @model_validator(mode="after")
    def validate_unique_choices(self) -> MLAnalysisConfig:
        if len(self.entity_types) != len(set(self.entity_types)):
            raise ValueError("ML entity types cannot be repeated.")
        if len(self.algorithms) != len(set(self.algorithms)):
            raise ValueError("ML algorithms cannot be repeated.")
        return self


class AnalysisSubmission(BaseModel):
    """Immutable snapshot of the analysis pipeline configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analysis_cutoff: datetime | None = None
    detection_enabled: bool = True
    detection_config: DetectionConfig = Field(default_factory=DetectionConfig)
    risk_scoring_enabled: bool = True
    risk_scoring_config: RiskScoringConfig = Field(default_factory=RiskScoringConfig)
    ml: MLAnalysisConfig = Field(default_factory=MLAnalysisConfig)

    @field_validator("analysis_cutoff")
    @classmethod
    def normalize_cutoff(cls, value: datetime | None) -> datetime | None:
        return (
            normalize_utc(value, field_name="analysis_cutoff")
            if value is not None
            else None
        )


class AnalysisJobResponse(BaseModel):
    """Safe job representation without Celery result or exception internals."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    dataset_id: UUID
    status: AnalysisJobState
    progress_percent: int = Field(ge=0, le=100)
    current_stage: str | None
    retry_count: int = Field(ge=0)
    cancel_requested: bool
    result_summary: dict[str, Any] | None
    error_summary: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AnalysisCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: AnalysisJobResponse
    cancellation: Literal["accepted", "already_requested", "already_finished"]
