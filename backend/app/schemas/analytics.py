"""Response DTOs for dataset, account, risk, and ML analytics."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import AnalysisJobResponse
from app.schemas.findings import RiskAssessmentResponse, RiskSummaryResponse
from app.schemas.graph import AccountNetworkSummary


class CurrencyAnalyticsTotal(BaseModel):
    currency: str
    transaction_count: int = Field(ge=0)
    total_amount: Decimal


class DatasetAnalyticsResponse(BaseModel):
    dataset_id: UUID
    dataset_name: str
    dataset_status: str
    is_synthetic: bool
    created_at: datetime
    account_count: int = Field(ge=0)
    transaction_count: int = Field(ge=0)
    transaction_volume_by_currency: list[CurrencyAnalyticsTotal]
    finding_summary: RiskSummaryResponse
    latest_analysis: AnalysisJobResponse | None


class AccountAnalyticsResponse(BaseModel):
    dataset_id: UUID
    account_id: UUID
    network: AccountNetworkSummary
    finding_count: int = Field(ge=0)
    open_finding_count: int = Field(ge=0)
    risk: RiskAssessmentResponse | None


class RiskScoreBand(BaseModel):
    risk_level: Literal["low", "medium", "high", "critical"]
    account_count: int = Field(ge=0)
    average_score: Decimal | None = Field(default=None, ge=0, le=1)


class RiskDistributionResponse(BaseModel):
    dataset_id: UUID
    accounts_by_risk_level: list[RiskScoreBand]
    unscored_account_count: int = Field(ge=0)
    latest_account_assessment_at: datetime | None
    findings_by_risk_level: dict[str, int]


class MLModelMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    model_name: str
    model_version: str
    feature_schema_version: str
    entity_type: Literal["ACCOUNT", "TRANSACTION"]
    training_dataset_id: UUID | None
    training_timestamp: datetime
    training_sample_count: int = Field(ge=2)
    feature_names: list[str]
    model_parameters: dict[str, Any]
    preprocessing_config: dict[str, Any]
    evaluation_metrics: dict[str, Any] | None
    random_seed: int
    status: Literal["TRAINED", "EVALUATED", "ARCHIVED"]
    created_at: datetime
