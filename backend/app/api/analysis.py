"""Authenticated, owner-scoped asynchronous analysis job endpoints."""

from __future__ import annotations

import hashlib
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.core.model_base import utc_now
from app.core.observability import request_id_context
from app.core.rate_limit import SensitiveWriteRateLimit
from app.models import AnalysisJob, User
from app.schemas.analysis import (
    AnalysisCancelResponse,
    AnalysisJobResponse,
    AnalysisJobState,
    AnalysisSubmission,
)
from app.schemas.pagination import PageResponse, page_response
from app.services.analysis_jobs import (
    AnalysisConcurrencyLimit,
    AnalysisJobNotFound,
    api_state,
    create_analysis_job,
    get_analysis_job,
    list_analysis_jobs,
    mark_enqueue_failed,
    request_job_cancellation,
)
from app.services.dataset_access import DatasetScopeNotFound, require_owned_dataset
from app.tasks.analysis import execute_analysis_task
from app.tasks.celery_app import (
    ANALYSIS_QUEUE,
    BrokerUnavailable,
    celery_app,
    ensure_broker_available,
)

logger = logging.getLogger("muletrace.api.analysis")
router = APIRouter(tags=["Analysis Jobs"])


def _response(job: AnalysisJob) -> AnalysisJobResponse:
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


def _digest_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not 8 <= len(value) <= 128 or any(
        ord(character) < 0x21 or ord(character) > 0x7E for character in value
    ):
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must contain 8 to 128 visible ASCII characters.",
        )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _enqueue_failed(db: Session, job: AnalysisJob, exc: Exception) -> None:
    mark_enqueue_failed(
        db,
        job_id=job.id,
        safe_error="The background queue could not accept this analysis.",
    )
    logger.error(
        "analysis.enqueue.failed",
        extra={
            "analysis_job_id": str(job.id),
            "exception_type": type(exc).__name__,
        },
    )


@router.post(
    "/datasets/{dataset_id}/analysis",
    response_model=AnalysisJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit an asynchronous dataset analysis",
)
def submit_analysis(
    dataset_id: UUID,
    payload: AnalysisSubmission,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AnalysisJobResponse:
    digest = _digest_idempotency_key(idempotency_key)
    try:
        require_owned_dataset(db, dataset_id, actor.id)
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc

    now = payload.analysis_cutoff or utc_now()
    parameters = {
        "configuration": payload.model_dump(mode="json"),
        "analysis_cutoff": now.isoformat(),
    }
    try:
        job, created = create_analysis_job(
            db,
            dataset_id=dataset_id,
            actor=actor,
            parameters=parameters,
            idempotency_key=digest,
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except AnalysisConcurrencyLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Re-enqueue a pending idempotent job with its same task ID if a prior
    # publish was ambiguous. PostgreSQL task claiming prevents double work.
    if created or job.status == "pending":
        try:
            ensure_broker_available()
            execute_analysis_task.apply_async(
                args=[str(job.id)],
                task_id=job.task_id,
                queue=ANALYSIS_QUEUE,
                serializer="json",
                headers={"request_id": request_id_context.get()},
            )
        except BrokerUnavailable as exc:
            if created:
                _enqueue_failed(db, job, exc)
            raise HTTPException(
                status_code=503,
                detail="The background analysis queue could not accept this job.",
            ) from exc
        except Exception as exc:
            if created:
                _enqueue_failed(db, job, exc)
            raise HTTPException(
                status_code=503,
                detail="The background analysis queue could not accept this job.",
            ) from exc
    return _response(job)


@router.get(
    "/datasets/{dataset_id}/analysis",
    response_model=PageResponse[AnalysisJobResponse],
    summary="List analysis jobs for an owned dataset",
)
def list_dataset_analysis(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    job_status: Annotated[AnalysisJobState | None, Query(alias="status")] = None,
) -> PageResponse[AnalysisJobResponse]:
    try:
        require_owned_dataset(db, dataset_id, actor.id)
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    jobs, total = list_analysis_jobs(
        db,
        dataset_id=dataset_id,
        actor=actor,
        page=page,
        page_size=page_size,
        status=job_status,
    )
    return page_response(
        items=[_response(job) for job in jobs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{dataset_id}/analysis/{job_id}",
    response_model=AnalysisJobResponse,
    summary="Read analysis progress and safe results",
)
def read_dataset_analysis(
    dataset_id: UUID,
    job_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> AnalysisJobResponse:
    try:
        require_owned_dataset(db, dataset_id, actor.id)
        job = get_analysis_job(
            db, dataset_id=dataset_id, job_id=job_id, actor=actor
        )
    except (DatasetScopeNotFound, AnalysisJobNotFound) as exc:
        raise HTTPException(status_code=404, detail="Analysis job not found.") from exc
    return _response(job)


@router.post(
    "/datasets/{dataset_id}/analysis/{job_id}/cancel",
    response_model=AnalysisCancelResponse,
    summary="Request cancellation of an analysis job",
)
def cancel_dataset_analysis(
    dataset_id: UUID,
    job_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
) -> AnalysisCancelResponse:
    try:
        require_owned_dataset(db, dataset_id, actor.id)
        job, outcome, task_id = request_job_cancellation(
            db, dataset_id=dataset_id, job_id=job_id, actor=actor
        )
    except (DatasetScopeNotFound, AnalysisJobNotFound) as exc:
        raise HTTPException(status_code=404, detail="Analysis job not found.") from exc
    if task_id is not None:
        try:
            celery_app.control.revoke(task_id, terminate=False)
        except Exception as exc:  # noqa: BLE001 - cancellation remains recorded even if revoke fails.
            logger.warning(
                "analysis.cancel.revoke_failed",
                extra={
                    "analysis_job_id": str(job.id),
                    "exception_type": type(exc).__name__,
                },
            )
    return AnalysisCancelResponse(job=_response(job), cancellation=outcome)
