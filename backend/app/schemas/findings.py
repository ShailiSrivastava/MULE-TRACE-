"""Request and response schemas for finding lifecycle and risk summaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import FindingStatus

FindingSeverity = Literal["info", "low", "medium", "high", "critical"]
RiskLevel = Literal["low", "medium", "high", "critical"]
FindingSortField = Literal[
    "created_at", "first_detected_at", "last_detected_at", "severity", "status"
]


class FindingStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FindingStatus
    reason: str | None = Field(default=None, max_length=2_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Reason cannot be blank.")
        return normalized

    @model_validator(mode="after")
    def terminal_states_require_reason(self) -> FindingStatusUpdate:
        if self.status in {FindingStatus.RESOLVED, FindingStatus.DISMISSED} and not self.reason:
            raise ValueError("A reason is required to resolve or dismiss a finding.")
        return self


class FindingAssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to_id: UUID | None


class FindingAccountReference(BaseModel):
    account_id: UUID
    relationship_role: str


class FindingTransactionReference(BaseModel):
    transaction_id: UUID
    evidence_role: str


class FindingObservationResponse(BaseModel):
    analysis_job_id: UUID
    observed_at: datetime


class FindingStatusHistoryResponse(BaseModel):
    id: UUID
    from_status: FindingStatus | None
    to_status: FindingStatus
    reason: str | None
    changed_by_id: UUID | None
    changed_at: datetime


class RiskAssessmentResponse(BaseModel):
    score: Decimal = Field(ge=0, le=1)
    risk_level: RiskLevel
    scoring_model_version: str
    score_components: dict[str, Any]
    assessed_at: datetime
    analysis_job_id: UUID


class FindingListItem(BaseModel):
    id: UUID
    dataset_id: UUID
    detector_name: str
    detector_version: str
    category: str
    severity: FindingSeverity
    title: str
    explanation: str
    deduplication_key: str
    status: FindingStatus
    assigned_to_id: UUID | None
    first_detected_at: datetime
    last_detected_at: datetime
    event_window_start: datetime | None
    event_window_end: datetime | None
    account_count: int
    transaction_count: int
    risk_score: Decimal | None
    risk_level: RiskLevel | None
    scoring_model_version: str | None
    created_at: datetime
    updated_at: datetime


class FindingDetail(FindingListItem):
    parameters: dict[str, Any]
    evidence: dict[str, Any]
    accounts: list[FindingAccountReference]
    transactions: list[FindingTransactionReference]
    observations: list[FindingObservationResponse]
    status_history: list[FindingStatusHistoryResponse]


class RiskSummaryResponse(BaseModel):
    dataset_id: UUID
    total_findings: int
    findings_by_category: dict[str, int]
    findings_by_severity: dict[str, int]
    findings_by_status: dict[str, int]
    findings_by_risk_level: dict[str, int]
    affected_account_count: int
    affected_transaction_count: int
    latest_analysis_at: datetime | None


class AccountRiskSummary(BaseModel):
    dataset_id: UUID
    account_id: UUID
    risk: RiskAssessmentResponse
    distinct_finding_count: int


def normalize_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamps must include a timezone offset.")
    return value.astimezone(UTC)
