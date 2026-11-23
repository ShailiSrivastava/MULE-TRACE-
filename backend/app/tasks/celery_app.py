"""Celery configuration using MuleTrace's existing Redis service."""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_ready, worker_shutdown
from kombu import Queue

from app.core.config import settings

ANALYSIS_QUEUE = "muletrace.analysis"
MAINTENANCE_QUEUE = "muletrace.maintenance"
logger = logging.getLogger("muletrace.worker")

celery_app = Celery(
    "muletrace",
    broker=settings.celery_broker_url,
    include=["app.tasks.analysis"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    result_backend=None,
    task_default_queue=ANALYSIS_QUEUE,
    task_queues=(Queue(ANALYSIS_QUEUE), Queue(MAINTENANCE_QUEUE)),
    task_routes={
        "muletrace.analysis.execute": {"queue": ANALYSIS_QUEUE},
        "muletrace.analysis.recover_stale": {"queue": MAINTENANCE_QUEUE},
    },
    task_create_missing_queues=False,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=True,
    task_default_delivery_mode="persistent",
    task_publish_retry=False,
    worker_prefetch_multiplier=1,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    broker_connection_timeout=settings.ANALYSIS_BROKER_CONNECT_TIMEOUT,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=5,
    broker_transport_options={
        "visibility_timeout": settings.ANALYSIS_STALE_JOB_SECONDS + 60
    },
    task_soft_time_limit=settings.ANALYSIS_TASK_SOFT_TIME_LIMIT,
    task_time_limit=settings.ANALYSIS_TASK_TIME_LIMIT,
    task_track_started=False,
    beat_schedule={
        "recover-stale-analysis-jobs": {
            "task": "muletrace.analysis.recover_stale",
            "schedule": 60.0,
            "options": {"queue": MAINTENANCE_QUEUE},
        }
    },
)


class BrokerUnavailable(RuntimeError):
    """Raised when Redis cannot accept a new background task."""


def ensure_broker_available() -> None:
    """Make one bounded authenticated broker connection check."""
    try:
        with celery_app.connection_for_write() as connection:
            connection.ensure_connection(max_retries=0)
    except Exception as exc:  # Redis clients expose transport-specific failures.
        raise BrokerUnavailable("The background queue is unavailable.") from exc


@worker_ready.connect
def recover_jobs_on_worker_start(sender=None, **kwargs) -> None:
    """Trigger a stale-job sweep when an analysis worker comes online."""
    try:
        celery_app.send_task(
            "muletrace.analysis.recover_stale",
            queue=MAINTENANCE_QUEUE,
        )
    except Exception as exc:  # noqa: BLE001 - keep worker startup observable and secrets private.
        logger.error(
            "analysis.recovery.schedule_failed",
            extra={"exception_type": type(exc).__name__},
        )


@worker_shutdown.connect
def log_worker_shutdown(sender=None, **kwargs) -> None:
    logger.info("analysis.worker.shutdown_requested")
