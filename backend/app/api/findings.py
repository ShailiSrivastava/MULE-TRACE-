"""Authenticated, dataset-owner-scoped finding and risk APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user, require_roles
from app.core.database import get_db
from app.models import FindingStatus, User, UserRole
from app.schemas.findings import (
    AccountRiskSummary,
    FindingAccountReference,
    FindingAssignmentUpdate,
    FindingDetail,
    FindingListItem,
    FindingObservationResponse,
    FindingSeverity,
    FindingStatusHistoryResponse,
    FindingStatusUpdate,
    FindingTransactionReference,
    RiskAssessmentResponse,
    RiskLevel,
    RiskSummaryResponse,
    normalize_utc,
)
from app.schemas.pagination import PageResponse, page_response
from app.services.dataset_access import DatasetScopeNotFound
from app.services.finding_queries import (
    get_account_risk,
    get_finding_detail,
    get_risk_summary,
    list_findings,
)
from app.services.findings import (
    FindingNotFound,
    FindingPermissionDenied,
    FindingPersistenceConflict,
    FindingPersistenceError,
    InvalidAssignee,
    InvalidFindingTransition,
    assign_finding,
    transition_finding_status,
)

router = APIRouter(tags=["Findings and Risk"])


def _risk_response(assessment) -> RiskAssessmentResponse | None:
    if assessment is None:
        return None
    return RiskAssessmentResponse(
        score=assessment.score,
        risk_level=assessment.risk_level,
        scoring_model_version=assessment.scoring_model_version,
        score_components=assessment.score_components,
        assessed_at=assessment.assessed_at,
        analysis_job_id=assessment.analysis_job_id,
    )


def _list_item(row) -> FindingListItem:
    finding, account_count, transaction_count, score, risk_level, version = row
    return FindingListItem(
        id=finding.id,
        dataset_id=finding.dataset_id,
        detector_name=finding.detector_name,
        detector_version=finding.detector_version,
        category=finding.category,
        severity=finding.severity,
        title=finding.title,
        explanation=finding.explanation,
        deduplication_key=finding.deduplication_key,
        status=finding.status,
        assigned_to_id=finding.assigned_to_id,
        first_detected_at=finding.first_detected_at,
        last_detected_at=finding.last_detected_at,
        event_window_start=finding.event_window_start,
        event_window_end=finding.event_window_end,
        account_count=int(account_count),
        transaction_count=int(transaction_count),
        risk_score=score,
        risk_level=risk_level,
        scoring_model_version=version,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
    )


def _raise_dataset_not_found(exc: DatasetScopeNotFound) -> None:
    raise HTTPException(status_code=404, detail="Dataset not found.") from exc


def _raise_finding_error(exc: Exception) -> None:
    if isinstance(exc, DatasetScopeNotFound):
        _raise_dataset_not_found(exc)
    if isinstance(exc, FindingNotFound):
        raise HTTPException(status_code=404, detail="Finding not found.") from exc
    if isinstance(exc, FindingPersistenceConflict):
        raise HTTPException(status_code=409, detail="Finding update conflicts with existing data.") from exc
    if isinstance(exc, FindingPersistenceError):
        raise HTTPException(status_code=503, detail="Finding service is unavailable.") from exc
    if isinstance(exc, InvalidFindingTransition):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, InvalidAssignee):
        raise HTTPException(status_code=422, detail="Assignee must be an active investigator.") from exc
    if isinstance(exc, FindingPermissionDenied):
        raise HTTPException(status_code=403, detail="You do not have permission to update findings.") from exc
    raise exc


@router.get(
    "/datasets/{dataset_id}/findings",
    response_model=PageResponse[FindingListItem],
    summary="List findings in an owned dataset",
)
def list_dataset_findings(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    category: Annotated[str | None, Query(max_length=100)] = None,
    severity: FindingSeverity | None = None,
    risk_level: RiskLevel | None = None,
    finding_status: Annotated[FindingStatus | None, Query(alias="status")] = None,
    assigned_to_id: UUID | None = None,
    unassigned: bool = False,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sort_by: Literal[
        "created_at", "first_detected_at", "last_detected_at", "severity", "status"
    ] = "last_detected_at",
    sort_order: Literal["asc", "desc"] = "desc",
) -> PageResponse[FindingListItem]:
    if assigned_to_id is not None and unassigned:
        raise HTTPException(
            status_code=422,
            detail="assigned_to_id and unassigned cannot be used together.",
        )
    try:
        normalized_start = normalize_utc(start_at)
        normalized_end = normalize_utc(end_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if normalized_start is not None and normalized_end is not None and normalized_start > normalized_end:
        raise HTTPException(status_code=422, detail="start_at must not follow end_at.")
    try:
        rows, total = list_findings(
            db,
            dataset_id=dataset_id,
            actor=actor,
            page=page,
            page_size=page_size,
            category=category,
            severity=severity,
            risk_level=risk_level,
            status=finding_status.value if finding_status else None,
            assigned_to_id=assigned_to_id,
            unassigned=unassigned,
            start_at=normalized_start,
            end_at=normalized_end,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except DatasetScopeNotFound as exc:
        _raise_dataset_not_found(exc)
    return page_response(
        items=[_list_item(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{dataset_id}/findings/{finding_id}",
    response_model=FindingDetail,
    summary="Retrieve a finding and its evidence",
)
def read_dataset_finding(
    dataset_id: UUID,
    finding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> FindingDetail:
    try:
        finding, accounts, transactions, observations, history, risk = get_finding_detail(
            db,
            dataset_id=dataset_id,
            finding_id=finding_id,
            actor=actor,
        )
    except (DatasetScopeNotFound, FindingNotFound) as exc:
        _raise_finding_error(exc)
    base = FindingListItem(
        id=finding.id,
        dataset_id=finding.dataset_id,
        detector_name=finding.detector_name,
        detector_version=finding.detector_version,
        category=finding.category,
        severity=finding.severity,
        title=finding.title,
        explanation=finding.explanation,
        deduplication_key=finding.deduplication_key,
        status=finding.status,
        assigned_to_id=finding.assigned_to_id,
        first_detected_at=finding.first_detected_at,
        last_detected_at=finding.last_detected_at,
        event_window_start=finding.event_window_start,
        event_window_end=finding.event_window_end,
        account_count=len(accounts),
        transaction_count=len(transactions),
        risk_score=risk.score if risk else None,
        risk_level=risk.risk_level if risk else None,
        scoring_model_version=risk.scoring_model_version if risk else None,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
    )
    return FindingDetail(
        **base.model_dump(),
        parameters=finding.parameters,
        evidence=finding.evidence,
        accounts=[
            FindingAccountReference(
                account_id=item.account_id,
                relationship_role=item.relationship_role,
            )
            for item in accounts
        ],
        transactions=[
            FindingTransactionReference(
                transaction_id=item.transaction_id,
                evidence_role=item.evidence_role,
            )
            for item in transactions
        ],
        observations=[
            FindingObservationResponse(
                analysis_job_id=item.analysis_job_id,
                observed_at=item.observed_at,
            )
            for item in observations
        ],
        status_history=[
            FindingStatusHistoryResponse(
                id=item.id,
                from_status=item.from_status,
                to_status=item.to_status,
                reason=item.reason,
                changed_by_id=item.changed_by_id,
                changed_at=item.changed_at,
            )
            for item in history
        ],
    )


@router.patch(
    "/datasets/{dataset_id}/findings/{finding_id}/status",
    response_model=FindingDetail,
    summary="Change finding lifecycle status",
)
def patch_finding_status(
    dataset_id: UUID,
    finding_id: UUID,
    payload: FindingStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.INVESTIGATOR)),
    ],
) -> FindingDetail:
    try:
        transition_finding_status(
            db,
            dataset_id=dataset_id,
            finding_id=finding_id,
            actor=actor,
            new_status=payload.status,
            reason=payload.reason,
        )
    except (
        DatasetScopeNotFound,
        FindingNotFound,
        FindingPermissionDenied,
        FindingPersistenceConflict,
        FindingPersistenceError,
        InvalidFindingTransition,
    ) as exc:
        _raise_finding_error(exc)
    return read_dataset_finding(dataset_id, finding_id, db, actor)


@router.patch(
    "/datasets/{dataset_id}/findings/{finding_id}/assignment",
    response_model=FindingDetail,
    summary="Assign a finding to an investigator",
)
def patch_finding_assignment(
    dataset_id: UUID,
    finding_id: UUID,
    payload: FindingAssignmentUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[
        User,
        Depends(require_roles(UserRole.ADMIN, UserRole.INVESTIGATOR)),
    ],
) -> FindingDetail:
    try:
        assign_finding(
            db,
            dataset_id=dataset_id,
            finding_id=finding_id,
            actor=actor,
            assignee_id=payload.assigned_to_id,
        )
    except (
        DatasetScopeNotFound,
        FindingNotFound,
        FindingPermissionDenied,
        FindingPersistenceConflict,
        FindingPersistenceError,
        InvalidAssignee,
    ) as exc:
        _raise_finding_error(exc)
    return read_dataset_finding(dataset_id, finding_id, db, actor)


@router.get(
    "/datasets/{dataset_id}/risk-summary",
    response_model=RiskSummaryResponse,
    summary="Summarize findings and risk in an owned dataset",
)
def read_risk_summary(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> RiskSummaryResponse:
    try:
        summary = get_risk_summary(db, dataset_id=dataset_id, actor=actor)
    except DatasetScopeNotFound as exc:
        _raise_dataset_not_found(exc)
    return RiskSummaryResponse(**summary)


@router.get(
    "/datasets/{dataset_id}/accounts/{account_id}/risk",
    response_model=AccountRiskSummary,
    summary="Retrieve the latest account risk assessment",
)
def read_account_risk(
    dataset_id: UUID,
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> AccountRiskSummary:
    try:
        assessment, finding_count = get_account_risk(
            db,
            dataset_id=dataset_id,
            account_id=account_id,
            actor=actor,
        )
    except DatasetScopeNotFound as exc:
        _raise_dataset_not_found(exc)
    except FindingNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found.") from exc
    if assessment is None:
        raise HTTPException(status_code=404, detail="Risk assessment not found.")
    return AccountRiskSummary(
        dataset_id=dataset_id,
        account_id=account_id,
        risk=_risk_response(assessment),
        distinct_finding_count=finding_count,
    )
