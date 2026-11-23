"""Typed, deterministic contracts shared by pure detection algorithms."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.graph.models import normalize_utc

DetectorSeverity = Literal["info", "low", "medium", "high", "critical"]
DetectorState = Literal["succeeded", "failed", "disabled"]
DETECTION_NAMESPACE = UUID("7581095d-25d4-4de7-8b0c-511f54406653")


class DetectionWindow(BaseModel):
    """Inclusive extent of matched event timestamps, normalized to UTC."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def timestamps_are_utc(cls, value: datetime) -> datetime:
        return normalize_utc(value, field_name="detection timestamp")

    @model_validator(mode="after")
    def ordered_window(self) -> DetectionWindow:
        if self.start_at > self.end_at:
            raise ValueError("Detection window start must not follow its end.")
        return self


class DetectionFinding(BaseModel):
    """Neutral evidence-backed indicator; it is not a risk score or alert."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: UUID
    deduplication_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    detector_name: str
    detector_version: str
    category: str
    severity: DetectorSeverity
    title: str
    explanation: str
    dataset_id: UUID | None
    account_ids: tuple[UUID, ...]
    transaction_ids: tuple[UUID, ...]
    time_window: DetectionWindow | None
    evidence: dict[str, Any]
    parameters: dict[str, Any]


class DetectorExecution(BaseModel):
    """Deterministic run metadata for one enabled, disabled, or failed detector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detector_name: str
    detector_version: str
    state: DetectorState
    finding_count: int = Field(ge=0)
    statistics: dict[str, int | bool | str] = Field(default_factory=dict)
    error_code: str | None = None
    error_type: str | None = None
    message: str | None = None


class DetectionRunResult(BaseModel):
    """Deterministically ordered in-memory results from an orchestrator run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: UUID | None
    findings: tuple[DetectionFinding, ...]
    executions: tuple[DetectorExecution, ...]


def _iso(value: datetime | None) -> str | None:
    return (
        normalize_utc(value, field_name="detection timestamp")
        .isoformat()
        .replace("+00:00", "Z")
        if value
        else None
    )


def create_finding(
    *,
    detector_name: str,
    detector_version: str,
    category: str,
    severity: DetectorSeverity,
    title: str,
    explanation: str,
    dataset_id: UUID | None,
    account_ids: tuple[UUID, ...] | list[UUID],
    transaction_ids: tuple[UUID, ...] | list[UUID],
    start_at: datetime | None,
    end_at: datetime | None,
    evidence: dict[str, Any],
    parameters: dict[str, Any],
    deduplication_context: tuple[str, ...] = (),
) -> DetectionFinding:
    """Build a finding whose UUID and dedup key depend only on stable inputs."""

    ordered_accounts = tuple(dict.fromkeys(account_ids))
    ordered_transactions = tuple(dict.fromkeys(transaction_ids))
    canonical = "\x1f".join(
        (
            str(dataset_id or "no-dataset"),
            detector_name,
            detector_version,
            category,
            ",".join(sorted(map(str, ordered_accounts))),
            ",".join(map(str, ordered_transactions)),
            _iso(start_at) or "",
            _iso(end_at) or "",
            "\x1e".join(deduplication_context),
        )
    )
    key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    identifier = uuid5(DETECTION_NAMESPACE, key)
    window = (
        DetectionWindow(start_at=start_at, end_at=end_at)
        if start_at is not None and end_at is not None
        else None
    )
    return DetectionFinding(
        finding_id=identifier,
        deduplication_key=key,
        detector_name=detector_name,
        detector_version=detector_version,
        category=category,
        severity=severity,
        title=title,
        explanation=explanation,
        dataset_id=dataset_id,
        account_ids=ordered_accounts,
        transaction_ids=ordered_transactions,
        time_window=window,
        evidence=evidence,
        parameters=parameters,
    )
