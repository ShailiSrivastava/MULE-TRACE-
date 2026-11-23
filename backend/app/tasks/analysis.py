"""Celery entry points for analysis execution and stale-job recovery."""

from __future__ import annotations

import logging
from uuid import UUID

from celery.exceptions import MaxRetriesExceededError

from app.analysis.pipeline import (
    AnalysisCancelled,
    AnalysisExecutionFenced,
    AnalysisStageFailure,
    execute_analysis_pipeline,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.analysis_jobs import (
    fail_analysis_job,
    finish_cancelled_job,
    job_cancellation_requested,
    mark_safe_dispatch_failure,
    recover_stale_jobs,
    schedule_job_retry,
)
from app.tasks.celery_app import ANALYSIS_QUEUE, celery_app

logger = logging.getLogger("muletrace.worker")


class AnalysisTaskFailure(RuntimeError):
    """Sanitized failure raised after the job record has been updated."""


class SafeRetryError(RuntimeError):
    """Retry signal with a non-sensitive explanation."""


def _fail_job(job_id: UUID, task_id: str, stage: str, message: str, error_type: str) -> None:
    try:
        with SessionLocal() as db:
            fail_analysis_job(
                db,
                job_id=job_id,
                task_id=task_id,
                stage=stage,
                safe_error=message,
                error_type=error_type,
            )
    except Exception as exc:  # noqa: BLE001 - failure recording must not hide worker errors.
        logger.error(
            "analysis.job.failure_record_failed",
            extra={
                "analysis_job_id": str(job_id),
                "stage": stage,
                "exception_type": type(exc).__name__,
            },
        )


@celery_app.task(
    bind=True,
    name="muletrace.analysis.execute",
    max_retries=settings.ANALYSIS_MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def execute_analysis_task(self, job_id: str) -> dict[str, str]:
    """Run one job; the only serialized argument is its stable UUID string."""
    identifier = UUID(job_id)
    task_id = str(self.request.id)
    logger.info(
        "analysis.task.received",
        extra={"analysis_job_id": str(identifier), "queue": ANALYSIS_QUEUE},
    )
    try:
        result = execute_analysis_pipeline(job_id=identifier, task_id=task_id)
    except AnalysisCancelled:
        logger.info(
            "analysis.task.cancelled",
            extra={"analysis_job_id": str(identifier)},
        )
        return {"status": "CANCELLED"}
    except AnalysisExecutionFenced:
        logger.info(
            "analysis.task.fenced",
            extra={"analysis_job_id": str(identifier)},
        )
        return {"status": "IGNORED"}
    except AnalysisStageFailure as failure:
        if failure.transient:
            try:
                with SessionLocal() as db:
                    if job_cancellation_requested(
                        db, job_id=identifier, task_id=task_id
                    ):
                        finish_cancelled_job(db, job_id=identifier, task_id=task_id)
                        return {"status": "CANCELLED"}
                    retry_count = schedule_job_retry(
                        db,
                        job_id=identifier,
                        task_id=task_id,
                        stage=failure.stage,
                    )
            except Exception as exc:  # noqa: BLE001 - keep retries isolated from transport errors.
                logger.error(
                    "analysis.task.retry_schedule_failed",
                    extra={
                        "analysis_job_id": str(identifier),
                        "stage": failure.stage,
                        "exception_type": type(exc).__name__,
                    },
                )
                raise AnalysisTaskFailure(
                    "A temporary analysis service error prevented retry scheduling."
                ) from None
            if retry_count is not None:
                countdown = min(2 ** min(retry_count, 6), 60)
                logger.warning(
                    "analysis.task.retrying",
                    extra={
                        "analysis_job_id": str(identifier),
                        "stage": failure.stage,
                        "retry_count": retry_count,
                        "duration_ms": countdown * 1_000,
                    },
                )
                try:
                    raise self.retry(
                        exc=SafeRetryError("A temporary analysis service error occurred."),
                        countdown=countdown,
                        max_retries=settings.ANALYSIS_MAX_RETRIES,
                    )
                except MaxRetriesExceededError:
                    _fail_job(
                        identifier,
                        task_id,
                        failure.stage,
                        failure.safe_message,
                        failure.error_type,
                    )
                    raise AnalysisTaskFailure(failure.safe_message) from None

        _fail_job(
            identifier,
            task_id,
            failure.stage,
            failure.safe_message,
            failure.error_type,
        )
        logger.error(
            "analysis.task.failed",
            extra={
                "analysis_job_id": str(identifier),
                "stage": failure.stage,
                "exception_type": failure.error_type,
            },
        )
        raise AnalysisTaskFailure(failure.safe_message) from None
    except Exception as exc:  # noqa: BLE001 - persist a sanitized terminal state.
        message = "The analysis pipeline failed; internal details are withheld."
        _fail_job(identifier, task_id, "analysis", message, type(exc).__name__)
        logger.error(
            "analysis.task.failed",
            extra={
                "analysis_job_id": str(identifier),
                "stage": "analysis",
                "exception_type": type(exc).__name__,
            },
        )
        raise AnalysisTaskFailure(message) from None
    logger.info(
        "analysis.task.finished",
        extra={
            "analysis_job_id": str(identifier),
            "status": result.get("status", "unknown"),
        },
    )
    return {"status": result.get("status", "unknown").upper()}


@celery_app.task(
    name="muletrace.analysis.recover_stale",
    ignore_result=True,
)
def recover_stale_analysis_jobs_task() -> dict[str, int]:
    """Recover stale PostgreSQL jobs and enqueue them with fenced task IDs."""
    with SessionLocal() as db:
        dispatch = recover_stale_jobs(db)
    enqueued = failed = 0
    for job_id, task_id in dispatch:
        try:
            execute_analysis_task.apply_async(
                args=[str(job_id)],
                task_id=task_id,
                queue=ANALYSIS_QUEUE,
                serializer="json",
            )
            enqueued += 1
        except Exception:  # noqa: BLE001 - a queue transport may expose vendor-specific errors.
            failed += 1
            with SessionLocal() as db:
                mark_safe_dispatch_failure(db, job_id=job_id, task_id=task_id)
            logger.error(
                "analysis.job.recovery_enqueue_failed",
                extra={"analysis_job_id": str(job_id)},
            )
    logger.info(
        "analysis.recovery.finished",
        extra={"recovered_count": enqueued, "failed_count": failed},
    )
    return {"recovered_count": enqueued, "failed_count": failed}
