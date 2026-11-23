"""Request and response DTOs for investigation case workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.pagination import PageResponse

CaseStatus = Literal["open", "in_review", "resolved", "closed"]
CasePriority = Literal["low", "medium", "high", "urgent"]


def _clean_nonempty(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Value must not be blank.")
    return cleaned


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20_000)
    category: str = Field(default="general", min_length=1, max_length=80)
    priority: CasePriority = "medium"

    @field_validator("title", "category")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _clean_nonempty(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20_000)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    priority: CasePriority | None = None
    status: CaseStatus | None = None

    @field_validator("title", "category")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _clean_nonempty(value) if value is not None else None

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_changes(self) -> CaseUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one case field must be provided.")
        return self


class InvestigatorSummary(BaseModel):
    id: UUID
    display_name: str | None
    role: str
    is_active: bool


class CaseResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    title: str
    description: str | None
    category: str
    priority: CasePriority
    status: CaseStatus
    created_by_id: UUID | None
    created_by: InvestigatorSummary | None = None
    assigned_to_id: UUID | None
    assigned_to: InvestigatorSummary | None = None
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    account_count: int = Field(ge=0)
    finding_count: int = Field(ge=0)
    note_count: int = Field(ge=0)


class CaseAccountLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CaseAccountLinkResponse(BaseModel):
    dataset_id: UUID
    case_id: UUID
    account_id: UUID
    account_type: str | None
    institution_code: str | None
    country_code: str | None
    evidence_snapshot: dict[str, Any] | None
    note: str | None
    added_by_id: UUID | None
    linked_at: datetime
    removed_at: datetime | None


class CaseFindingLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: UUID
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class CaseFindingLinkResponse(BaseModel):
    dataset_id: UUID
    case_id: UUID
    finding_id: UUID
    category: str
    severity: str
    status: str
    title: str
    explanation: str
    evidence_snapshot: dict[str, Any]
    note: str | None
    linked_by_id: UUID | None
    linked_at: datetime
    removed_at: datetime | None


class CaseAssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to_id: UUID | None


class CaseAssignmentHistoryItem(BaseModel):
    audit_id: UUID
    event_type: str
    previous_assignee_id: UUID | None
    assigned_to_id: UUID | None
    actor: InvestigatorSummary | None
    created_at: datetime


class CaseAssignmentsResponse(BaseModel):
    case_id: UUID
    current_assignee: InvestigatorSummary | None
    history: PageResponse[CaseAssignmentHistoryItem]


class CaseNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return _clean_nonempty(value)


class CaseNoteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        return _clean_nonempty(value)


class CaseNoteResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    case_id: UUID
    author_id: UUID | None
    author: InvestigatorSummary | None
    content: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    revision_count: int = Field(ge=1)


class CaseNoteRevisionResponse(BaseModel):
    id: UUID
    note_id: UUID
    revision_number: int = Field(ge=1)
    content: str
    edited_by_id: UUID | None
    edited_by: InvestigatorSummary | None
    created_at: datetime


class CaseTimelineEventResponse(BaseModel):
    id: UUID
    event_type: str
    actor_id: UUID | None
    actor_name: str | None
    actor_role: str | None
    created_at: datetime
    metadata: dict[str, Any]
