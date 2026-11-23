"""Analysis job configuration, API, and PostgreSQL lifecycle service tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import analysis as analysis_api
from app.core.config import Settings, settings
from app.core.database import get_db
from app.core.model_base import Base, utc_now
from app.main import app
from app.models import AnalysisJob, AuditLog, Dataset, User
from app.security.tokens import create_access_token
from app.services.analysis_jobs import (
    AnalysisConcurrencyLimit,
    claim_analysis_job,
    create_analysis_job,
    fail_analysis_job,
    finish_cancelled_job,
    job_cancellation_requested,
    record_job_stage,
    recover_stale_jobs,
    request_job_cancellation,
    schedule_job_retry,
    start_job_stage,
)
from app.tasks.celery_app import ANALYSIS_QUEUE, celery_app

JWT_SECRET = "phase-eleven-test-secret-long-enough-for-jwt-security"


@pytest.fixture
def analysis_context(monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(JWT_SECRET))
    monkeypatch.setattr(analysis_api, "ensure_broker_available", lambda: None)
    dispatched: list[dict] = []
    monkeypatch.setattr(
        analysis_api.execute_analysis_task,
        "apply_async",
        lambda **kwargs: dispatched.append(kwargs),
    )

    owner = User(
        email=f"analysis-owner-{uuid4().hex}@example.com",
        password_hash="test-hash",
    )
    other_owner = User(
        email=f"analysis-other-{uuid4().hex}@example.com",
        password_hash="test-hash",
    )
    with factory() as db:
        db.add_all([owner, other_owner])
        db.flush()
        dataset = Dataset(owner_id=owner.id, name="Analysis dataset")
        other_dataset = Dataset(owner_id=other_owner.id, name="Private dataset")
        db.add_all([dataset, other_dataset])
        db.commit()
        for item in (owner, other_owner, dataset, other_dataset):
            db.refresh(item)

    with TestClient(app) as client:
        yield {
            "client": client,
            "factory": factory,
            "owner": owner,
            "other_owner": other_owner,
            "dataset": dataset,
            "other_dataset": other_dataset,
            "owner_headers": {
                "Authorization": f"Bearer {create_access_token(owner.id)}"
            },
            "other_headers": {
                "Authorization": f"Bearer {create_access_token(other_owner.id)}"
            },
            "dispatched": dispatched,
        }
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_celery_configuration_uses_json_and_isolated_queues():
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.result_backend is None
    assert ANALYSIS_QUEUE in {queue.name for queue in celery_app.conf.task_queues}
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.task_soft_time_limit < celery_app.conf.task_time_limit
    assert "recover-stale-analysis-jobs" in celery_app.conf.beat_schedule
    assert "muletrace.analysis.execute" in celery_app.tasks
    assert "muletrace.analysis.recover_stale" in celery_app.tasks


def test_redis_broker_url_encodes_password_and_settings_bound_limits(monkeypatch):
    for name in (
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_DB",
        "REDIS_PASSWORD",
        "REDIS_PASSWORD_FILE",
        "CELERY_BROKER_URL",
        "CELERY_BROKER_URL_FILE",
    ):
        monkeypatch.delenv(name, raising=False)
    configured = Settings(
        _env_file=None,
        REDIS_HOST="redis.internal",
        REDIS_PORT=6390,
        REDIS_DB=2,
        REDIS_PASSWORD="p@ss word:/",
    )
    assert configured.celery_broker_url == (
        "redis://:p%40ss%20word%3A%2F@redis.internal:6390/2"
    )

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ANALYSIS_TASK_SOFT_TIME_LIMIT=90,
            ANALYSIS_TASK_TIME_LIMIT=90,
        )


def test_analysis_api_submission_status_idempotency_and_cancellation(analysis_context):
    client = analysis_context["client"]
    dataset_id = analysis_context["dataset"].id
    headers = analysis_context["owner_headers"] | {"Idempotency-Key": "run-001-key"}
    path = f"/api/v1/datasets/{dataset_id}/analysis"

    first = client.post(path, json={}, headers=headers)
    assert first.status_code == 202
    first_body = first.json()
    assert first_body["status"] == "QUEUED"
    assert first_body["progress_percent"] == 0
    assert "task_id" not in first_body
    assert "parameters" not in first_body
    assert len(analysis_context["dispatched"]) == 1
    assert analysis_context["dispatched"][0]["args"] == [first_body["id"]]
    assert analysis_context["dispatched"][0]["serializer"] == "json"

    repeated = client.post(path, json={}, headers=headers)
    assert repeated.status_code == 202
    assert repeated.json()["id"] == first_body["id"]

    detail = client.get(f"{path}/{first_body['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "QUEUED"

    listing = client.get(
        path,
        params={"page": 1, "page_size": 1, "status": "QUEUED"},
        headers=analysis_context["owner_headers"],
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == first_body["id"]
    completed_filter = client.get(
        path,
        params={"status": "COMPLETED"},
        headers=analysis_context["owner_headers"],
    )
    assert completed_filter.status_code == 200
    assert completed_filter.json()["total"] == 0

    cancelled = client.post(
        f"{path}/{first_body['id']}/cancel", headers=analysis_context["owner_headers"]
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["job"]["status"] == "CANCELLED"
    assert cancelled.json()["cancellation"] == "accepted"


def test_analysis_api_requires_auth_and_hides_other_users_datasets(analysis_context):
    client = analysis_context["client"]
    dataset_id = analysis_context["dataset"].id
    other_dataset_id = analysis_context["other_dataset"].id
    path = f"/api/v1/datasets/{dataset_id}/analysis"

    assert client.get(path).status_code == 401
    assert (
        client.post(path, json={}, headers=analysis_context["other_headers"]).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/datasets/{other_dataset_id}/analysis",
            headers=analysis_context["owner_headers"],
        ).status_code
        == 404
    )


def test_analysis_api_rejects_invalid_options_and_broker_failure(analysis_context, monkeypatch):
    client = analysis_context["client"]
    dataset_id = analysis_context["dataset"].id
    path = f"/api/v1/datasets/{dataset_id}/analysis"
    headers = analysis_context["owner_headers"]

    invalid = client.post(path, json={"unexpected": "field"}, headers=headers)
    assert invalid.status_code == 422
    invalid_key = client.post(
        path,
        json={},
        headers=headers | {"Idempotency-Key": "short"},
    )
    assert invalid_key.status_code == 422

    def broker_unavailable():
        raise analysis_api.BrokerUnavailable("private broker error")

    monkeypatch.setattr(analysis_api, "ensure_broker_available", broker_unavailable)
    unavailable = client.post(path, json={}, headers=headers)
    assert unavailable.status_code == 503
    assert "private broker error" not in unavailable.text
    with analysis_context["factory"]() as db:
        job = db.scalar(select(AnalysisJob).order_by(AnalysisJob.created_at.desc()))
        assert job.status == "failed"
        assert job.error_message == "The background queue could not accept this analysis."


def test_analysis_job_service_enforces_concurrency_and_recovers_stale_work(
    analysis_context, monkeypatch
):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_ACTIVE_PER_DATASET", 1)
    factory = analysis_context["factory"]
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]

    with factory() as db:
        first, created = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {}},
            idempotency_key=None,
        )
        assert created is True
        old_task_id = first.task_id
        assert claim_analysis_job(db, job_id=first.id, task_id=old_task_id)
        assert start_job_stage(
            db,
            job_id=first.id,
            task_id=old_task_id,
            stage="graph_loading",
            progress_percent=10,
        )
        first.heartbeat_at = utc_now() - timedelta(seconds=10_000)
        db.commit()

        with pytest.raises(AnalysisConcurrencyLimit):
            create_analysis_job(
                db,
                dataset_id=dataset.id,
                actor=owner,
                parameters={"configuration": {}},
                idempotency_key=None,
            )

        dispatch = recover_stale_jobs(db)
        assert len(dispatch) == 1
        recovered_id, recovered_task_id = dispatch[0]
        assert recovered_id == first.id
        assert recovered_task_id != old_task_id
        db.refresh(first)
        assert first.status == "pending"
        assert first.retry_count == 1
        assert first.current_stage == "recovered"
        assert first.result_summary["stages"]["graph_loading"]["status"] == "retrying"
        assert db.scalar(
            select(AuditLog).where(AuditLog.event_type == "analysis.job.recovered")
        )


def test_stale_job_fails_safely_after_retry_limit(analysis_context, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_RETRIES", 1)
    factory = analysis_context["factory"]
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]
    with factory() as db:
        job, _ = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {}},
            idempotency_key=None,
        )
        task_id = job.task_id
        assert claim_analysis_job(db, job_id=job.id, task_id=task_id)
        assert start_job_stage(
            db,
            job_id=job.id,
            task_id=task_id,
            stage="graph_loading",
            progress_percent=10,
        )
        job.retry_count = 1
        job.heartbeat_at = utc_now() - timedelta(seconds=10_000)
        db.commit()

        assert recover_stale_jobs(db) == []
        db.refresh(job)
        assert job.status == "failed"
        assert job.current_stage == "recovery"
        assert job.result_summary["stages"]["graph_loading"]["status"] == "failed"
        assert job.error_message == "The worker stopped before completing this analysis."


def test_job_claim_and_completion_fence_duplicate_or_invalid_transitions(analysis_context):
    from app.services.analysis_jobs import complete_analysis_job

    factory = analysis_context["factory"]
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]
    with factory() as db:
        job, _ = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {}},
            idempotency_key=None,
        )
        job_id = job.id
        task_id = job.task_id
        assert claim_analysis_job(db, job_id=job_id, task_id="stale-task") is False
        assert (
            complete_analysis_job(
                db, job_id=job_id, task_id=task_id, summary={"finding_count": 0}
            )
            is None
        )
        assert claim_analysis_job(db, job_id=job_id, task_id=task_id)
        assert claim_analysis_job(db, job_id=job_id, task_id=task_id) is False
        assert (
            complete_analysis_job(
                db, job_id=job_id, task_id="stale-task", summary={"finding_count": 0}
            )
            is None
        )
        assert (
            complete_analysis_job(
                db, job_id=job_id, task_id=task_id, summary={"finding_count": 0}
            )
            == "completed"
        )
        assert (
            complete_analysis_job(
                db, job_id=job_id, task_id=task_id, summary={"finding_count": 0}
            )
            is None
        )
        db.refresh(job)
        assert job.status == "completed"


def test_duplicate_idempotency_key_returns_existing_without_new_audit(analysis_context):
    factory = analysis_context["factory"]
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]
    with factory() as db:
        original, created = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {"detection_enabled": True}},
            idempotency_key="same-key-digest",
        )
        assert created
        repeated, repeated_created = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {"detection_enabled": False}},
            idempotency_key="same-key-digest",
        )
        assert repeated_created is False
        assert repeated.id == original.id
        assert repeated.parameters["configuration"]["detection_enabled"] is True
        audits = db.scalars(
            select(AuditLog).where(AuditLog.event_type == "analysis.job.submitted")
        ).all()
        assert len(audits) == 1


def test_running_job_cancellation_commits_at_stage_boundary(analysis_context):
    factory = analysis_context["factory"]
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]
    with factory() as db:
        job, _ = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {}},
            idempotency_key=None,
        )
        task_id = job.task_id
        assert claim_analysis_job(db, job_id=job.id, task_id=task_id)
        assert start_job_stage(
            db, job_id=job.id, task_id=task_id, stage="configuration", progress_percent=3
        )
        assert record_job_stage(
            db,
            job_id=job.id,
            task_id=task_id,
            stage="configuration",
            state="completed",
            progress_percent=5,
            statistics={"validated": True},
        )
        assert start_job_stage(
            db, job_id=job.id, task_id=task_id, stage="detection", progress_percent=25
        )

        cancelling, outcome, revoke_task_id = request_job_cancellation(
            db, dataset_id=dataset.id, job_id=job.id, actor=owner
        )
        assert outcome == "accepted"
        assert revoke_task_id is None
        assert cancelling.status == "running"
        assert job_cancellation_requested(db, job_id=job.id, task_id=task_id)
        assert finish_cancelled_job(db, job_id=job.id, task_id=task_id)
        db.refresh(job)
        assert job.status == "cancelled"
        assert job.current_stage == "cancelled"
        assert job.finished_at is not None


def test_partial_stage_failure_is_terminal_and_exposes_only_safe_summary(analysis_context):
    factory = analysis_context["factory"]
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]
    with factory() as db:
        job, _ = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {}},
            idempotency_key=None,
        )
        task_id = job.task_id
        assert claim_analysis_job(db, job_id=job.id, task_id=task_id)
        assert start_job_stage(
            db, job_id=job.id, task_id=task_id, stage="configuration", progress_percent=3
        )
        assert record_job_stage(
            db,
            job_id=job.id,
            task_id=task_id,
            stage="configuration",
            state="completed",
            progress_percent=5,
            statistics={"validated": True},
        )
        assert start_job_stage(
            db, job_id=job.id, task_id=task_id, stage="detection", progress_percent=25
        )
        assert record_job_stage(
            db,
            job_id=job.id,
            task_id=task_id,
            stage="detection",
            state="partial",
            progress_percent=40,
            statistics={"finding_count": 3, "failed_detector_count": 1},
        )
        assert fail_analysis_job(
            db,
            job_id=job.id,
            task_id=task_id,
            stage="detection",
            safe_error="Configured detection could not complete.",
            error_type="DetectorExecutionFailure",
        )
        db.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "Configured detection could not complete."
        assert job.result_summary["partial_completion"] is True
        assert job.result_summary["stages"]["detection"]["status"] == "failed"
        assert job.result_summary["stages"]["configuration"]["duration_ms"] >= 0
        assert "traceback" not in str(job.result_summary).lower()


def test_transient_retry_is_bounded_and_persists_retry_count(analysis_context, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_RETRIES", 1)
    factory = analysis_context["factory"]
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]
    with factory() as db:
        job, _ = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {}},
            idempotency_key=None,
        )
        task_id = job.task_id
        assert claim_analysis_job(db, job_id=job.id, task_id=task_id)
        assert schedule_job_retry(
            db, job_id=job.id, task_id=task_id, stage="graph_loading"
        ) == 1
        db.refresh(job)
        assert job.status == "pending"
        assert job.retry_count == 1
        assert claim_analysis_job(db, job_id=job.id, task_id=task_id)
        assert (
            schedule_job_retry(
                db, job_id=job.id, task_id=task_id, stage="graph_loading"
            )
            is None
        )


def test_pipeline_completes_with_disabled_stages_recorded_as_skipped(
    analysis_context, monkeypatch
):
    from app.analysis import pipeline
    from app.schemas.analysis import AnalysisSubmission

    factory = analysis_context["factory"]
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]
    configuration = AnalysisSubmission(
        analysis_cutoff=datetime.now(UTC),
        detection_enabled=False,
        risk_scoring_enabled=False,
        ml={"enabled": False},
    )
    with factory() as db:
        job, _ = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={
                "configuration": configuration.model_dump(mode="json"),
                "analysis_cutoff": configuration.analysis_cutoff.isoformat(),
            },
            idempotency_key=None,
        )
        job_id = job.id
        task_id = job.task_id

    result = pipeline.execute_analysis_pipeline(job_id=job_id, task_id=task_id)
    duplicate_delivery = pipeline.execute_analysis_pipeline(
        job_id=job_id, task_id=task_id
    )

    with factory() as db:
        job = db.get(AnalysisJob, job_id)
        assert result["status"] == "completed"
        assert duplicate_delivery["status"] == "ignored"
        assert job.status == "completed"
        assert job.progress_percent == 100
        assert job.result_summary["stages"]["graph_loading"]["status"] == "completed"
        assert job.result_summary["stages"]["detection"]["status"] == "skipped"
        assert job.result_summary["stages"]["risk_scoring"]["status"] == "skipped"
        assert job.result_summary["stages"]["ml_inference"]["status"] == "skipped"


def test_task_records_sanitized_permanent_failure(analysis_context, monkeypatch):
    from app.analysis.pipeline import AnalysisStageFailure
    from app.tasks import analysis as task_module

    factory = analysis_context["factory"]
    owner = analysis_context["owner"]
    dataset = analysis_context["dataset"]
    monkeypatch.setattr(task_module, "SessionLocal", factory)
    with factory() as db:
        job, _ = create_analysis_job(
            db,
            dataset_id=dataset.id,
            actor=owner,
            parameters={"configuration": {}},
            idempotency_key=None,
        )
        job_id = job.id
        task_id = job.task_id

    def fail_pipeline(*, job_id, task_id):
        raise AnalysisStageFailure(
            stage="graph_loading",
            error_type="OperationalError",
            transient=False,
            safe_message="The dataset graph could not be loaded.",
        )

    monkeypatch.setattr(task_module, "execute_analysis_pipeline", fail_pipeline)
    result = task_module.execute_analysis_task.apply(
        args=[str(job_id)], task_id=task_id, throw=False
    )

    with factory() as db:
        job = db.get(AnalysisJob, job_id)
        assert result.failed()
        assert job.status == "failed"
        assert job.error_message == "The dataset graph could not be loaded."
        assert "OperationalError" not in job.error_message


def test_analysis_cutoff_is_timezone_aware_and_normalized():
    from app.schemas.analysis import AnalysisSubmission

    normalized = AnalysisSubmission.model_validate(
        {"analysis_cutoff": "2026-11-22T10:00:00+05:30"}
    )
    assert normalized.analysis_cutoff == datetime(2026, 11, 22, 4, 30, tzinfo=UTC)

    with pytest.raises(ValidationError):
        AnalysisSubmission.model_validate(
            {"analysis_cutoff": "2026-11-22T10:00:00"}
        )
