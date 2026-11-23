"""PostgreSQL-backed analysis job lifecycle and concurrency controls."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.model_base import utc_now
from app.core.observability import request_id_context
from app.models import AnalysisJob, AuditLog, Dataset, User
from app.services.dataset_access import DatasetScopeNotFound

FINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})
ACTIVE_JOB_STATUSES = ("pending", "running")


class AnalysisJobNotFound(LookupError):
    """Raised for a missing job or one outside the requested owned dataset."""


class AnalysisConcurrencyLimit(RuntimeError):
    """Raised when configured active-job limits have been reached."""


class AnalysisJobConflict(RuntimeError):
    """Raised when a job lifecycle operation is not valid in its current state."""


def database_state(api_state: str) -> str:
    return {"QUEUED": "pending"}.get(api_state, api_state.lower())


def api_state(db_state: str) -> str:
    return {"pending": "QUEUED"}.get(db_state, db_state.upper())


def _audit(
    db: Session,
    *,
    job: AnalysisJob,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=job.created_by_id,
            event_type=event_type,
            entity_type="analysis_job",
            entity_id=job.id,
            request_id=request_id_context.get(),
            details={
                "dataset_id": str(job.dataset_id),
                **(details or {}),
            },
        )
    )


def create_analysis_job(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    parameters: dict[str, Any],
    idempotency_key: str | None,
) -> tuple[AnalysisJob, bool]:
    """Create and commit one immutable configuration snapshot.

    Dataset and user row locks serialize the two configured concurrency limits.
    A database unique constraint is the final idempotency protection.
    """
    dataset = db.scalar(
        select(Dataset)
        .where(Dataset.id == dataset_id, Dataset.owner_id == actor.id)
        .with_for_update()
    )
    if dataset is None:
        raise DatasetScopeNotFound

    if idempotency_key is not None:
        existing = db.scalar(
            select(AnalysisJob).where(
                AnalysisJob.dataset_id == dataset_id,
                AnalysisJob.created_by_id == actor.id,
                AnalysisJob.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing, False

    db.scalar(select(User.id).where(User.id == actor.id).with_for_update())
    dataset_active = db.scalar(
        select(func.count(AnalysisJob.id)).where(
            AnalysisJob.dataset_id == dataset_id,
            AnalysisJob.status.in_(ACTIVE_JOB_STATUSES),
            AnalysisJob.job_type == "full_analysis",
        )
    ) or 0
    if dataset_active >= settings.ANALYSIS_MAX_ACTIVE_PER_DATASET:
        raise AnalysisConcurrencyLimit(
            "The dataset already has the maximum number of active analyses."
        )

    user_active = db.scalar(
        select(func.count(AnalysisJob.id)).where(
            AnalysisJob.created_by_id == actor.id,
            AnalysisJob.status.in_(ACTIVE_JOB_STATUSES),
            AnalysisJob.job_type == "full_analysis",
        )
    ) or 0
    if user_active >= settings.ANALYSIS_MAX_ACTIVE_PER_USER:
        raise AnalysisConcurrencyLimit(
            "The user already has the maximum number of active analyses."
        )

    now = utc_now()
    job = AnalysisJob(
        dataset_id=dataset_id,
        created_by_id=actor.id,
        job_type="full_analysis",
        status="pending",
        parameters=parameters,
        progress_percent=0,
        current_stage="queued",
        retry_count=0,
        task_id=str(uuid4()),
        idempotency_key=idempotency_key,
        heartbeat_at=now,
    )
    db.add(job)
    try:
        db.flush()
        _audit(
            db,
            job=job,
            event_type="analysis.job.submitted",
            details={"status": "pending"},
        )
        db.commit()
        db.refresh(job)
        return job, True
    except IntegrityError:
        db.rollback()
        if idempotency_key is not None:
            existing = db.scalar(
                select(AnalysisJob).where(
                    AnalysisJob.dataset_id == dataset_id,
                    AnalysisJob.created_by_id == actor.id,
                    AnalysisJob.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return existing, False
        raise


def get_analysis_job(
    db: Session, *, dataset_id: UUID, job_id: UUID, actor: User
) -> AnalysisJob:
    job = db.scalar(
        select(AnalysisJob).where(
            AnalysisJob.dataset_id == dataset_id,
            AnalysisJob.id == job_id,
            AnalysisJob.created_by_id == actor.id,
        )
    )
    if job is None:
        raise AnalysisJobNotFound
    return job


def list_analysis_jobs(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    status: str | None = None,
) -> tuple[list[AnalysisJob], int]:
    filters = [
        AnalysisJob.dataset_id == dataset_id,
        AnalysisJob.created_by_id == actor.id,
        AnalysisJob.job_type == "full_analysis",
    ]
    if status is not None:
        filters.append(AnalysisJob.status == database_state(status))
    total = int(db.scalar(select(func.count(AnalysisJob.id)).where(*filters)) or 0)
    rows = db.scalars(
        select(AnalysisJob)
        .where(*filters)
        .order_by(AnalysisJob.created_at.desc(), AnalysisJob.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def request_job_cancellation(
    db: Session, *, dataset_id: UUID, job_id: UUID, actor: User
) -> tuple[AnalysisJob, str, str | None]:
    job = db.scalar(
        select(AnalysisJob)
        .where(
            AnalysisJob.dataset_id == dataset_id,
            AnalysisJob.id == job_id,
            AnalysisJob.created_by_id == actor.id,
            AnalysisJob.job_type == "full_analysis",
        )
        .with_for_update()
    )
    if job is None:
        raise AnalysisJobNotFound
    if job.status == "pending":
        job.status = "cancelled"
        job.current_stage = "cancelled"
        job.finished_at = utc_now()
        job.updated_at = utc_now()
        _audit(db, job=job, event_type="analysis.job.cancelled")
        outcome = "accepted"
    elif job.status == "running":
        if job.cancel_requested_at is not None:
            outcome = "already_requested"
        else:
            job.cancel_requested_at = utc_now()
            job.updated_at = utc_now()
            _audit(db, job=job, event_type="analysis.job.cancellation_requested")
            outcome = "accepted"
    elif job.status == "cancelled":
        outcome = "already_requested"
    else:
        outcome = "already_finished"
    task_id = job.task_id if outcome == "accepted" and job.status == "cancelled" else None
    db.commit()
    db.refresh(job)
    return job, outcome, task_id


def claim_analysis_job(db: Session, *, job_id: UUID, task_id: str) -> bool:
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update())
    if (
        job is None
        or job.job_type != "full_analysis"
        or job.task_id != task_id
        or job.status != "pending"
    ):
        return False
    now = utc_now()
    job.status = "running"
    job.started_at = job.started_at or now
    job.current_stage = "starting"
    job.heartbeat_at = now
    job.updated_at = now
    _audit(db, job=job, event_type="analysis.job.started")
    db.commit()
    return True


def job_cancellation_requested(db: Session, *, job_id: UUID, task_id: str) -> bool:
    job = db.scalar(
        select(AnalysisJob).where(
            AnalysisJob.id == job_id,
            AnalysisJob.task_id == task_id,
        )
    )
    return job is None or job.status == "cancelled" or job.cancel_requested_at is not None


def start_job_stage(
    db: Session,
    *,
    job_id: UUID,
    task_id: str,
    stage: str,
    progress_percent: int,
) -> bool:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if job is None or job.status != "running" or job.task_id != task_id:
        return False
    if job.cancel_requested_at is not None:
        return False
    now = utc_now()
    job.current_stage = stage
    job.progress_percent = progress_percent
    job.heartbeat_at = now
    job.updated_at = now
    summary = dict(job.result_summary or {})
    stages = dict(summary.get("stages", {}))
    stages[stage] = {"status": "running", "started_at": now.isoformat()}
    summary["stages"] = stages
    job.result_summary = summary
    db.commit()
    return True


def record_job_stage(
    db: Session,
    *,
    job_id: UUID,
    task_id: str,
    stage: str,
    state: str,
    progress_percent: int,
    statistics: dict[str, int | float | bool | str] | None = None,
) -> bool:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if job is None or job.status != "running" or job.task_id != task_id:
        return False
    now = utc_now()
    job.current_stage = stage
    job.progress_percent = progress_percent
    job.heartbeat_at = now
    job.updated_at = now
    summary = dict(job.result_summary or {})
    stages = dict(summary.get("stages", {}))
    previous = dict(stages.get(stage, {}))
    previous.update(
        {"status": state, "finished_at": now.isoformat()}
    )
    started_at = previous.get("started_at")
    if isinstance(started_at, str):
        try:
            previous["duration_ms"] = max(
                0,
                round(
                    (now - datetime.fromisoformat(started_at)).total_seconds() * 1000
                ),
            )
        except ValueError:
            pass
    if statistics is not None:
        previous["statistics"] = statistics
    stages[stage] = previous
    summary["stages"] = stages
    summary["partial_completion"] = any(
        value.get("status") in {"completed", "partial"}
        for value in stages.values()
    )
    job.result_summary = summary
    _audit(
        db,
        job=job,
        event_type=f"analysis.stage.{state}",
        details={"stage": stage},
    )
    db.commit()
    return True


def complete_analysis_job(
    db: Session,
    *,
    job_id: UUID,
    task_id: str,
    summary: dict[str, Any],
) -> str | None:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if job is None or job.status != "running" or job.task_id != task_id:
        return None
    now = utc_now()
    if job.cancel_requested_at is not None:
        job.status = "cancelled"
        job.current_stage = "cancelled"
        status = "cancelled"
        _audit(db, job=job, event_type="analysis.job.cancelled")
    else:
        job.status = "completed"
        job.current_stage = "completed"
        job.progress_percent = 100
        status = "completed"
        _audit(db, job=job, event_type="analysis.job.completed")
    existing = dict(job.result_summary or {})
    existing.update(summary)
    existing["partial_completion"] = status != "completed"
    job.result_summary = existing
    job.finished_at = now
    job.heartbeat_at = now
    job.updated_at = now
    job.error_message = None
    db.commit()
    return status


def finish_cancelled_job(db: Session, *, job_id: UUID, task_id: str) -> bool:
    """Commit cancellation only at a safe worker stage boundary."""
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if job is None or job.task_id != task_id:
        return False
    if job.status == "cancelled":
        return True
    if job.status != "running" or job.cancel_requested_at is None:
        return False
    now = utc_now()
    job.status = "cancelled"
    job.current_stage = "cancelled"
    job.finished_at = now
    job.heartbeat_at = now
    job.updated_at = now
    summary = dict(job.result_summary or {})
    summary["partial_completion"] = any(
        value.get("status") in {"completed", "partial"}
        for value in dict(summary.get("stages", {})).values()
    )
    job.result_summary = summary
    _audit(db, job=job, event_type="analysis.job.cancelled")
    db.commit()
    return True


def fail_analysis_job(
    db: Session,
    *,
    job_id: UUID,
    task_id: str,
    stage: str,
    safe_error: str,
    error_type: str,
) -> bool:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if job is None or job.task_id != task_id or job.status not in {"running", "pending"}:
        return False
    now = utc_now()
    job.status = "failed"
    job.current_stage = stage
    job.error_message = safe_error[:500]
    job.finished_at = now
    job.heartbeat_at = now
    job.updated_at = now
    summary = dict(job.result_summary or {})
    stages = dict(summary.get("stages", {}))
    stages[stage] = {
        **dict(stages.get(stage, {})),
        "status": "failed",
        "error": safe_error[:500],
        "error_type": error_type[:80],
        "finished_at": now.isoformat(),
    }
    summary["stages"] = stages
    summary["partial_completion"] = any(
        value.get("status") in {"completed", "partial"}
        for value in stages.values()
    )
    job.result_summary = summary
    _audit(
        db,
        job=job,
        event_type="analysis.job.failed",
        details={"stage": stage, "error_type": error_type[:80]},
    )
    db.commit()
    return True


def schedule_job_retry(
    db: Session,
    *,
    job_id: UUID,
    task_id: str,
    stage: str,
) -> int | None:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if (
        job is None
        or job.status != "running"
        or job.task_id != task_id
        or job.retry_count >= settings.ANALYSIS_MAX_RETRIES
    ):
        return None
    now = utc_now()
    job.status = "pending"
    job.retry_count += 1
    job.current_stage = f"retrying:{stage}"[:80]
    job.error_message = "A temporary service interruption occurred; retry scheduled."
    job.heartbeat_at = now
    job.updated_at = now
    stages = dict((job.result_summary or {}).get("stages", {}))
    stage_result = dict(stages.get(stage, {}))
    stage_result.update(
        {
            "status": "retrying",
            "error": job.error_message,
            "retry_count": job.retry_count,
            "finished_at": now.isoformat(),
        }
    )
    stages[stage] = stage_result
    summary = dict(job.result_summary or {})
    summary["stages"] = stages
    summary["partial_completion"] = any(
        value.get("status") in {"completed", "partial"}
        for value in stages.values()
    )
    job.result_summary = summary
    _audit(
        db,
        job=job,
        event_type="analysis.job.retry_scheduled",
        details={"stage": stage, "retry_count": job.retry_count},
    )
    db.commit()
    return job.retry_count


def mark_enqueue_failed(db: Session, *, job_id: UUID, safe_error: str) -> None:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if job is None or job.status != "pending":
        return
    now = utc_now()
    job.status = "failed"
    job.current_stage = "enqueue"
    job.error_message = safe_error[:500]
    job.finished_at = now
    job.updated_at = now
    _audit(db, job=job, event_type="analysis.job.enqueue_failed")
    db.commit()


def request_worker_cancellation(
    db: Session, *, job_id: UUID, task_id: str
) -> bool:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if job is None or job.task_id != task_id or job.status != "running":
        return False
    if job.cancel_requested_at is None:
        job.cancel_requested_at = utc_now()
        job.updated_at = utc_now()
        _audit(db, job=job, event_type="analysis.job.cancellation_requested")
        db.commit()
    return True


def _update_recovery_stage(
    job: AnalysisJob,
    *,
    now: datetime,
    state: str,
    safe_error: str | None = None,
    error_type: str | None = None,
) -> None:
    """Close the prior running stage when a stale task is cancelled or fenced."""
    summary = dict(job.result_summary or {})
    stages = dict(summary.get("stages", {}))
    stage_name = job.current_stage
    if not stage_name or stage_name not in stages:
        stage_name = "recovery"
    stage = dict(stages.get(stage_name, {}))
    stage.update({"status": state, "finished_at": now.isoformat()})
    if safe_error is not None:
        stage["error"] = safe_error[:500]
    if error_type is not None:
        stage["error_type"] = error_type[:80]
    stages[stage_name] = stage
    summary["stages"] = stages
    summary["partial_completion"] = any(
        value.get("status") in {"completed", "partial"}
        for value in stages.values()
    )
    job.result_summary = summary


def recover_stale_jobs(db: Session) -> list[tuple[UUID, str]]:
    """Fence and requeue stale analysis jobs or fail exhausted attempts."""
    stale_before = utc_now() - timedelta(seconds=settings.ANALYSIS_STALE_JOB_SECONDS)
    candidates = db.scalars(
        select(AnalysisJob)
        .where(
            AnalysisJob.job_type == "full_analysis",
            AnalysisJob.status.in_(ACTIVE_JOB_STATUSES),
            AnalysisJob.task_id.is_not(None),
            or_(
                AnalysisJob.heartbeat_at < stale_before,
                and_(
                    AnalysisJob.heartbeat_at.is_(None),
                    AnalysisJob.created_at < stale_before,
                ),
            ),
        )
        .order_by(AnalysisJob.created_at)
        .limit(100)
        .with_for_update(skip_locked=True)
    ).all()
    dispatch: list[tuple[UUID, str]] = []
    now = utc_now()
    for job in candidates:
        if job.cancel_requested_at is not None:
            job.status = "cancelled"
            job.finished_at = now
            job.heartbeat_at = now
            job.updated_at = now
            _update_recovery_stage(job, now=now, state="cancelled")
            job.current_stage = "cancelled"
            _audit(db, job=job, event_type="analysis.job.cancelled")
            continue
        if job.retry_count >= settings.ANALYSIS_MAX_RETRIES:
            safe_error = "The worker stopped before completing this analysis."
            job.status = "failed"
            job.error_message = safe_error
            job.finished_at = now
            job.heartbeat_at = now
            job.updated_at = now
            _update_recovery_stage(
                job,
                now=now,
                state="failed",
                safe_error=safe_error,
                error_type="StaleWorker",
            )
            job.current_stage = "recovery"
            _audit(
                db,
                job=job,
                event_type="analysis.job.failed",
                details={"stage": "recovery", "error_type": "StaleWorker"},
            )
            continue
        job.status = "pending"
        _update_recovery_stage(
            job,
            now=now,
            state="retrying",
            safe_error="The worker stopped; this analysis was requeued.",
        )
        job.retry_count += 1
        job.task_id = str(uuid4())
        job.current_stage = "recovered"
        job.error_message = "The worker stopped; this analysis was requeued."
        job.heartbeat_at = now
        job.updated_at = now
        _audit(
            db,
            job=job,
            event_type="analysis.job.recovered",
            details={"retry_count": job.retry_count},
        )
        dispatch.append((job.id, job.task_id))
    db.commit()
    return dispatch


def mark_safe_dispatch_failure(
    db: Session, *, job_id: UUID, task_id: str
) -> None:
    job = db.scalar(
        select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
    )
    if job is None or job.task_id != task_id or job.status != "pending":
        return
    now = utc_now()
    job.status = "failed"
    job.current_stage = "recovery"
    job.error_message = "The background queue could not accept the recovered analysis."
    job.finished_at = now
    job.updated_at = now
    _audit(db, job=job, event_type="analysis.job.recovery_enqueue_failed")
    db.commit()
