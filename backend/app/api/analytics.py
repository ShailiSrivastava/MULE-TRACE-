"""Authenticated, dataset-scoped analytics and ML metadata APIs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.graph.models import GraphFilters, GraphLimitExceeded
from app.models import AnalysisJob, FindingStatus, RiskAssessment, User
from app.schemas.analysis import AnalysisJobResponse
from app.schemas.analytics import (
    AccountAnalyticsResponse,
    DatasetAnalyticsResponse,
    MLModelMetadataResponse,
    RiskDistributionResponse,
    RiskScoreBand,
)
from app.schemas.findings import (
    FindingListItem,
    FindingSeverity,
    RiskAssessmentResponse,
    RiskLevel,
)
from app.schemas.graph import AccountNetworkSummary
from app.schemas.pagination import PageResponse, page_response
from app.services.analysis_jobs import api_state
from app.services.analytics_queries import (
    account_finding_counts,
    account_risk_distribution,
    dataset_analytics,
    list_dataset_ml_models,
)
from app.services.dataset_access import DatasetScopeNotFound
from app.services.finding_queries import get_account_risk, list_findings
from app.services.graph_queries import (
    AccountGraphNotFound,
    account_network_metrics,
)

router = APIRouter(tags=["Dataset Analytics"])


def _dataset_not_found(exc: DatasetScopeNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail="Dataset not found.")


def _graph_too_large(exc: GraphLimitExceeded) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail="The requested analytics graph exceeds supported limits.",
    )


def _account_risk(assessment: RiskAssessment | None) -> RiskAssessmentResponse | None:
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


def _analysis_job(job: AnalysisJob | None) -> AnalysisJobResponse | None:
    if job is None:
        return None
    return AnalysisJobResponse(
        id=job.id,
        dataset_id=job.dataset_id,
        status=api_state(job.status),
        progress_percent=job.progress_percent,
        current_stage=job.current_stage,
        retry_count=job.retry_count,
        cancel_requested=job.cancel_requested_at is not None,
        result_summary=job.result_summary,
        error_summary=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _finding_list_item(row) -> FindingListItem:
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


@router.get(
    "/datasets/{dataset_id}/analytics",
    response_model=DatasetAnalyticsResponse,
    summary="Read dataset and analysis analytics",
)
def read_dataset_analytics(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> DatasetAnalyticsResponse:
    try:
        result = dataset_analytics(db, dataset_id=dataset_id, actor=actor)
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    dataset = result["dataset"]
    return DatasetAnalyticsResponse(
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        dataset_status=dataset.status,
        is_synthetic=dataset.is_synthetic,
        created_at=dataset.created_at,
        account_count=result["account_count"],
        transaction_count=result["transaction_count"],
        transaction_volume_by_currency=result["transaction_volume_by_currency"],
        finding_summary=result["finding_summary"],
        latest_analysis=_analysis_job(result["latest_analysis"]),
    )


@router.get(
    "/datasets/{dataset_id}/accounts/{account_id}/analytics",
    response_model=AccountAnalyticsResponse,
    summary="Read account network, finding, and risk analytics",
)
def read_account_analytics(
    dataset_id: UUID,
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> AccountAnalyticsResponse:
    try:
        metrics = account_network_metrics(
            db,
            dataset_id=dataset_id,
            owner_id=actor.id,
            account_id=account_id,
            filters=GraphFilters(),
        )
        assessment, _ = get_account_risk(
            db,
            dataset_id=dataset_id,
            account_id=account_id,
            actor=actor,
        )
        finding_count, open_finding_count = account_finding_counts(
            db,
            dataset_id=dataset_id,
            account_id=account_id,
            actor=actor,
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    except AccountGraphNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found in dataset.") from exc
    except GraphLimitExceeded as exc:
        raise _graph_too_large(exc) from exc
    return AccountAnalyticsResponse(
        dataset_id=dataset_id,
        account_id=account_id,
        network=AccountNetworkSummary(dataset_id=dataset_id, **asdict(metrics)),
        finding_count=finding_count,
        open_finding_count=open_finding_count,
        risk=_account_risk(assessment),
    )


@router.get(
    "/datasets/{dataset_id}/analytics/risk-distribution",
    response_model=RiskDistributionResponse,
    summary="Summarize latest persisted risk scores",
)
def read_risk_distribution(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> RiskDistributionResponse:
    try:
        result = account_risk_distribution(db, dataset_id=dataset_id, actor=actor)
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    raw_bands = result["accounts_by_risk_level"]
    return RiskDistributionResponse(
        dataset_id=dataset_id,
        accounts_by_risk_level=[
            RiskScoreBand(
                risk_level=level,
                account_count=raw_bands.get(level, {}).get("account_count", 0),
                average_score=raw_bands.get(level, {}).get("average_score"),
            )
            for level in ("low", "medium", "high", "critical")
        ],
        unscored_account_count=result["unscored_account_count"],
        latest_account_assessment_at=result["latest_account_assessment_at"],
        findings_by_risk_level=result["findings_by_risk_level"],
    )


@router.get(
    "/datasets/{dataset_id}/analytics/ml/models",
    response_model=PageResponse[MLModelMetadataResponse],
    summary="List ML models registered for an owned dataset",
)
def read_dataset_ml_models(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    entity_type: Literal["ACCOUNT", "TRANSACTION"] | None = None,
    model_status: Annotated[
        Literal["TRAINED", "EVALUATED", "ARCHIVED"] | None,
        Query(alias="status"),
    ] = None,
    model_name: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
) -> PageResponse[MLModelMetadataResponse]:
    try:
        rows, total = list_dataset_ml_models(
            db,
            dataset_id=dataset_id,
            actor=actor,
            page=page,
            page_size=page_size,
            entity_type=entity_type,
            status=model_status,
            model_name=model_name,
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    return page_response(
        items=[MLModelMetadataResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{dataset_id}/analytics/ml/anomalies",
    response_model=PageResponse[FindingListItem],
    summary="List persisted ML anomaly findings",
)
def read_dataset_ml_anomalies(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    severity: FindingSeverity | None = None,
    finding_status: Annotated[FindingStatus | None, Query(alias="status")] = None,
    risk_level: RiskLevel | None = None,
    sort_by: Literal[
        "created_at", "first_detected_at", "last_detected_at", "severity", "status"
    ] = "last_detected_at",
    sort_order: Literal["asc", "desc"] = "desc",
) -> PageResponse[FindingListItem]:
    try:
        rows, total = list_findings(
            db,
            dataset_id=dataset_id,
            actor=actor,
            page=page,
            page_size=page_size,
            category="ml_anomaly",
            severity=severity,
            risk_level=risk_level,
            status=finding_status.value if finding_status else None,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    return page_response(
        items=[_finding_list_item(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
