"""Stage-by-stage analysis pipeline for one PostgreSQL-backed job."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.model_base import utc_now
from app.detection.orchestrator import run_detection
from app.graph.models import GraphFilters
from app.ml.clustering import KMeansAnomalyModel
from app.ml.features import FeatureBatch, extract_features
from app.ml.isolation_forest import IsolationForestModel
from app.ml.local_outlier_factor import LocalOutlierFactorModel
from app.ml.orchestrator import FittedAnomalyModel, fit_model, predict
from app.ml.phase9_adapter import predictions_to_detection_run
from app.ml.registry import ModelRegistry
from app.models import AnalysisJob, Dataset, User
from app.schemas.analysis import AnalysisAlgorithm, AnalysisSubmission
from app.services.analysis_jobs import (
    claim_analysis_job,
    complete_analysis_job,
    job_cancellation_requested,
    record_job_stage,
    start_job_stage,
)
from app.services.findings import persist_detection_run
from app.services.graph import build_owned_dataset_graph
from app.services.ml_registry import ensure_model_metadata
from app.services.risk_scoring import calculate_and_persist_risk_scores

logger = logging.getLogger("muletrace.analysis")


class AnalysisCancelled(RuntimeError):
    """Raised internally at a safe stage boundary after cancellation."""


class AnalysisExecutionFenced(RuntimeError):
    """A newer task owns the job; the stale worker must stop."""


@dataclass(frozen=True, slots=True)
class AnalysisStageFailure(RuntimeError):
    stage: str
    error_type: str
    transient: bool
    safe_message: str


def _exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def is_transient_analysis_error(exc: BaseException) -> bool:
    """Treat connection-level DB failures as retryable, not data errors."""
    for current in _exception_chain(exc):
        if isinstance(current, OperationalError):
            return True
        if isinstance(current, DBAPIError) and current.connection_invalidated:
            return True
    return False


_SAFE_FAILURES = {
    "configuration": "The submitted analysis configuration could not be loaded.",
    "graph_loading": "The dataset graph could not be loaded.",
    "detection": "One or more configured detection rules failed.",
    "finding_persistence": "Detection findings could not be persisted.",
    "risk_scoring": "Risk assessments could not be calculated.",
    "ml_feature_extraction": "ML features could not be extracted.",
    "ml_inference": "The configured ML model could not complete analysis.",
    "ml_finding_persistence": "ML findings could not be persisted.",
    "risk_scoring_after_ml": "Final risk assessments could not be calculated.",
    "analysis": "The analysis pipeline could not be completed.",
}


def _raise_stage_failure(stage: str, exc: BaseException) -> None:
    raise AnalysisStageFailure(
        stage=stage,
        error_type=type(exc).__name__,
        transient=is_transient_analysis_error(exc),
        safe_message=_SAFE_FAILURES.get(stage, "The analysis stage failed."),
    ) from None


def _begin_stage(
    db: Session, *, job_id: UUID, task_id: str, stage: str, progress: int
) -> None:
    if job_cancellation_requested(db, job_id=job_id, task_id=task_id):
        _finish_cancelled(db, job_id=job_id, task_id=task_id)
        raise AnalysisCancelled
    if not start_job_stage(
        db,
        job_id=job_id,
        task_id=task_id,
        stage=stage,
        progress_percent=progress,
    ):
        if job_cancellation_requested(db, job_id=job_id, task_id=task_id):
            _finish_cancelled(db, job_id=job_id, task_id=task_id)
            raise AnalysisCancelled
        raise AnalysisExecutionFenced


def _finish_cancelled(db: Session, *, job_id: UUID, task_id: str) -> None:
    from app.services.analysis_jobs import finish_cancelled_job

    finish_cancelled_job(db, job_id=job_id, task_id=task_id)


def _record_stage(
    db: Session,
    *,
    job_id: UUID,
    task_id: str,
    stage: str,
    state: str,
    progress: int,
    statistics: dict[str, int | float | bool | str],
) -> None:
    if not record_job_stage(
        db,
        job_id=job_id,
        task_id=task_id,
        stage=stage,
        state=state,
        progress_percent=progress,
        statistics=statistics,
    ):
        if job_cancellation_requested(db, job_id=job_id, task_id=task_id):
            _finish_cancelled(db, job_id=job_id, task_id=task_id)
            raise AnalysisCancelled
        raise AnalysisExecutionFenced


def _load_job_context(
    db: Session, *, job_id: UUID
) -> tuple[AnalysisJob, Dataset, User, AnalysisSubmission, datetime]:
    job = db.get(AnalysisJob, job_id)
    if job is None or job.job_type != "full_analysis":
        raise LookupError("The analysis job is unavailable.")
    dataset = db.get(Dataset, job.dataset_id)
    if dataset is None:
        raise LookupError("The analysis dataset is unavailable.")
    owner = db.get(User, dataset.owner_id)
    if owner is None or not owner.is_active:
        raise LookupError("The dataset owner is unavailable.")
    configuration = AnalysisSubmission.model_validate(
        job.parameters.get("configuration", {})
    )
    raw_cutoff = job.parameters.get("analysis_cutoff")
    cutoff = (
        datetime.fromisoformat(raw_cutoff)
        if isinstance(raw_cutoff, str)
        else configuration.analysis_cutoff or job.created_at
    )
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("Stored analysis cutoff is not timezone aware.")
    return job, dataset, owner, configuration, cutoff


def _make_estimator(
    algorithm: AnalysisAlgorithm, *, configuration: AnalysisSubmission, model_version: str
):
    ml_config = configuration.ml
    if algorithm == "isolation_forest":
        return IsolationForestModel(
            ml_config.isolation_forest.model_copy(update={"model_version": model_version})
        )
    if algorithm == "local_outlier_factor":
        return LocalOutlierFactorModel(
            ml_config.local_outlier_factor.model_copy(
                update={"model_version": model_version}
            )
        )
    return KMeansAnomalyModel(
        ml_config.kmeans.model_copy(update={"model_version": model_version})
    )


def _model_version(base_version: str, *, job_id: UUID, entity_type: str) -> str:
    prefix = base_version[:18]
    suffix = f"-{entity_type.lower()}-{job_id.hex[:12]}"
    return f"{prefix[: 40 - len(suffix)]}{suffix}"


def _run_ml(
    db: Session,
    *,
    batch: FeatureBatch,
    job: AnalysisJob,
    actor: User,
    configuration: AnalysisSubmission,
    analysis_timestamp: datetime,
) -> tuple[list[Any], list[dict[str, Any]]]:
    registry = ModelRegistry()
    predictions = []
    model_summaries: list[dict[str, Any]] = []
    entity_batches = {
        "ACCOUNT": batch.account_features,
        "TRANSACTION": batch.transaction_features,
    }
    config_fields = {
        "isolation_forest": configuration.ml.isolation_forest,
        "local_outlier_factor": configuration.ml.local_outlier_factor,
        "kmeans": configuration.ml.kmeans,
    }
    for entity_type in configuration.ml.entity_types:
        vectors = entity_batches[entity_type]
        for algorithm in configuration.ml.algorithms:
            config = config_fields[algorithm]
            version = _model_version(
                config.model_version, job_id=job.id, entity_type=entity_type
            )
            estimator = _make_estimator(
                algorithm, configuration=configuration, model_version=version
            )
            fitted = fit_model(
                vectors,
                estimator,
                training_timestamp=job.started_at or job.created_at,
            )
            ensure_model_metadata(db, actor=actor, metadata=fitted.metadata)
            registered = registry.register(
                metadata=fitted.metadata,
                estimator=fitted.estimator,
                preprocessor=fitted.preprocessor,
                explanation_baseline=fitted.explanation_baseline,
            )
            process_model = FittedAnomalyModel(
                estimator=registered.estimator,
                preprocessor=registered.preprocessor,
                metadata=registered.metadata,
                explanation_baseline=registered.explanation_baseline,
            )
            model_predictions = predict(
                process_model, vectors, analysis_timestamp=analysis_timestamp
            )
            predictions.extend(model_predictions)
            model_summaries.append(
                {
                    "model_name": fitted.metadata.model_name,
                    "model_version": fitted.metadata.model_version,
                    "entity_type": entity_type,
                    "sample_count": len(vectors),
                    "anomaly_count": sum(
                        prediction.prediction_label == "ANOMALY"
                        for prediction in model_predictions
                    ),
                }
            )
    return predictions, model_summaries


def execute_analysis_pipeline(*, job_id: UUID, task_id: str) -> dict[str, Any]:
    """Execute bounded pipeline stages with independent database commits."""
    with SessionLocal() as db:
        if not claim_analysis_job(db, job_id=job_id, task_id=task_id):
            return {"status": "ignored"}
        try:
            _begin_stage(
                db, job_id=job_id, task_id=task_id,
                stage="configuration", progress=3,
            )
            job, dataset, owner, configuration, cutoff = _load_job_context(
                db, job_id=job_id
            )
            _record_stage(
                db, job_id=job_id, task_id=task_id,
                stage="configuration", state="completed", progress=5,
                statistics={"validated": True},
            )
        except (AnalysisCancelled, AnalysisExecutionFenced):
            raise
        except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
            _raise_stage_failure("configuration", exc)

        analysis_timestamp = job.started_at or utc_now()
        logger.info(
            "analysis.job.started",
            extra={"analysis_job_id": str(job.id), "dataset_id": str(dataset.id)},
        )

        try:
            _begin_stage(
                db, job_id=job_id, task_id=task_id,
                stage="graph_loading", progress=10,
            )
            graph = build_owned_dataset_graph(
                db,
                dataset_id=dataset.id,
                owner_id=owner.id,
                filters=GraphFilters(end_at=cutoff + timedelta(microseconds=1)),
            )
            _record_stage(
                db, job_id=job_id, task_id=task_id,
                stage="graph_loading", state="completed", progress=20,
                statistics={"account_count": graph.number_of_nodes(),
                            "transaction_count": graph.number_of_edges()},
            )
        except (AnalysisCancelled, AnalysisExecutionFenced):
            raise
        except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
            _raise_stage_failure("graph_loading", exc)

        detection_findings = 0
        risk_counts = {"finding_assessments": 0, "account_assessments": 0}
        ml_finding_count = 0

        if configuration.detection_enabled:
            try:
                _begin_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="detection", progress=25,
                )
                detection_result = run_detection(
                    graph, configuration.detection_config, dataset_id=dataset.id
                )
                detection_findings = len(detection_result.findings)
                if detection_findings or detection_result.executions:
                    with SessionLocal() as persist_db:
                        actor = persist_db.get(User, owner.id)
                        if actor is None:
                            raise LookupError("The dataset owner is unavailable.")
                        persistence = persist_detection_run(
                            persist_db,
                            dataset_id=dataset.id,
                            analysis_job_id=job.id,
                            actor=actor,
                            result=detection_result,
                            observed_at=analysis_timestamp,
                        )
                    persist_statistics = {
                        "created_count": persistence.created_count,
                        "observed_count": persistence.observed_count,
                        "unchanged_count": persistence.unchanged_count,
                    }
                else:
                    persist_statistics = {
                        "created_count": 0,
                        "observed_count": 0,
                        "unchanged_count": 0,
                    }
                failed_detector_count = sum(
                    execution.state == "failed"
                    for execution in detection_result.executions
                )
                detection_state = "partial" if failed_detector_count else "completed"
                _record_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="detection", state=detection_state, progress=40,
                    statistics={
                        "finding_count": detection_findings,
                        "failed_detector_count": failed_detector_count,
                        "disabled_detector_count": sum(
                            execution.state == "disabled"
                            for execution in detection_result.executions
                        ),
                        **persist_statistics,
                    },
                )
                if failed_detector_count:
                    raise AnalysisStageFailure(
                        stage="detection",
                        error_type="DetectorExecutionFailure",
                        transient=False,
                        safe_message=_SAFE_FAILURES["detection"],
                    )
            except (AnalysisCancelled, AnalysisExecutionFenced, AnalysisStageFailure):
                raise
            except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
                _raise_stage_failure("detection", exc)
        else:
            _record_stage(
                db, job_id=job_id, task_id=task_id, stage="detection",
                state="skipped", progress=40, statistics={"reason": "disabled"},
            )

        if configuration.risk_scoring_enabled:
            try:
                _begin_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="risk_scoring", progress=45,
                )
                with SessionLocal() as score_db:
                    actor = score_db.get(User, owner.id)
                    if actor is None:
                        raise LookupError("The dataset owner is unavailable.")
                    _, score_result = calculate_and_persist_risk_scores(
                        score_db,
                        dataset_id=dataset.id,
                        analysis_job_id=job.id,
                        actor=actor,
                        config=configuration.risk_scoring_config,
                        assessed_at=analysis_timestamp,
                    )
                risk_counts = {
                    "finding_assessments": len(score_result.finding_scores),
                    "account_assessments": len(score_result.account_scores),
                }
                _record_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="risk_scoring", state="completed", progress=55,
                    statistics=risk_counts,
                )
            except (AnalysisCancelled, AnalysisExecutionFenced):
                raise
            except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
                _raise_stage_failure("risk_scoring", exc)
        else:
            _record_stage(
                db, job_id=job_id, task_id=task_id, stage="risk_scoring",
                state="skipped", progress=55, statistics={"reason": "disabled"},
            )

        if configuration.ml.enabled:
            try:
                _begin_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="ml_feature_extraction", progress=60,
                )
                batch = extract_features(graph, analysis_cutoff=cutoff)
                _record_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="ml_feature_extraction", state="completed", progress=68,
                    statistics={
                        "account_samples": len(batch.account_features),
                        "transaction_samples": len(batch.transaction_features),
                        "currency_count": len(batch.currencies),
                    },
                )
            except (AnalysisCancelled, AnalysisExecutionFenced):
                raise
            except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
                _raise_stage_failure("ml_feature_extraction", exc)

            try:
                _begin_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="ml_inference", progress=70,
                )
                with SessionLocal() as metadata_db:
                    actor = metadata_db.get(User, owner.id)
                    if actor is None:
                        raise LookupError("The dataset owner is unavailable.")
                    predictions, model_summaries = _run_ml(
                        metadata_db,
                        batch=batch,
                        job=job,
                        actor=actor,
                        configuration=configuration,
                        analysis_timestamp=analysis_timestamp,
                    )
                _record_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="ml_inference", state="completed", progress=82,
                    statistics={
                        "prediction_count": len(predictions),
                        "anomaly_count": sum(
                            item.prediction_label == "ANOMALY" for item in predictions
                        ),
                        "model_count": len(model_summaries),
                    },
                )
            except (AnalysisCancelled, AnalysisExecutionFenced):
                raise
            except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
                _raise_stage_failure("ml_inference", exc)

            try:
                _begin_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="ml_finding_persistence", progress=84,
                )
                ml_result = predictions_to_detection_run(
                    predictions, dataset_id=dataset.id
                )
                with SessionLocal() as persist_db:
                    actor = persist_db.get(User, owner.id)
                    if actor is None:
                        raise LookupError("The dataset owner is unavailable.")
                    ml_persistence = persist_detection_run(
                        persist_db,
                        dataset_id=dataset.id,
                        analysis_job_id=job.id,
                        actor=actor,
                        result=ml_result,
                        observed_at=analysis_timestamp,
                    )
                ml_finding_count = len(ml_result.findings)
                _record_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="ml_finding_persistence", state="completed", progress=90,
                    statistics={
                        "finding_count": ml_finding_count,
                        "created_count": ml_persistence.created_count,
                        "observed_count": ml_persistence.observed_count,
                        "unchanged_count": ml_persistence.unchanged_count,
                    },
                )
            except (AnalysisCancelled, AnalysisExecutionFenced):
                raise
            except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
                _raise_stage_failure("ml_finding_persistence", exc)

            if configuration.risk_scoring_enabled:
                try:
                    _begin_stage(
                        db, job_id=job_id, task_id=task_id,
                        stage="risk_scoring_after_ml", progress=92,
                    )
                    base = configuration.risk_scoring_config
                    ml_version = f"{base.model_version[:37]}-ml"
                    final_config = base.model_copy(
                        update={"model_version": ml_version}
                    )
                    with SessionLocal() as score_db:
                        actor = score_db.get(User, owner.id)
                        if actor is None:
                            raise LookupError("The dataset owner is unavailable.")
                        _, final_result = calculate_and_persist_risk_scores(
                            score_db,
                            dataset_id=dataset.id,
                            analysis_job_id=job.id,
                            actor=actor,
                            config=final_config,
                            assessed_at=analysis_timestamp,
                        )
                    risk_counts = {
                        "finding_assessments": len(final_result.finding_scores),
                        "account_assessments": len(final_result.account_scores),
                    }
                    _record_stage(
                        db, job_id=job_id, task_id=task_id,
                        stage="risk_scoring_after_ml", state="completed", progress=97,
                        statistics=risk_counts,
                    )
                except (AnalysisCancelled, AnalysisExecutionFenced):
                    raise
                except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
                    _raise_stage_failure("risk_scoring_after_ml", exc)
            else:
                _record_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage="risk_scoring_after_ml", state="skipped", progress=97,
                    statistics={"reason": "disabled"},
                )
        else:
            for stage, progress in (
                ("ml_feature_extraction", 68),
                ("ml_inference", 82),
                ("ml_finding_persistence", 90),
                ("risk_scoring_after_ml", 97),
            ):
                _record_stage(
                    db, job_id=job_id, task_id=task_id,
                    stage=stage, state="skipped", progress=progress,
                    statistics={"reason": "ml_disabled"},
                )

        final_summary = {
            "rule_finding_count": detection_findings,
            "ml_finding_count": ml_finding_count,
            "risk_assessment_count": sum(risk_counts.values()),
            "analysis_cutoff": cutoff.isoformat(),
        }
        try:
            completed_status = complete_analysis_job(
                db, job_id=job_id, task_id=task_id, summary=final_summary
            )
        except Exception as exc:  # noqa: BLE001 - convert stage failures to safe job errors.
            _raise_stage_failure("analysis", exc)
        if completed_status is None:
            raise AnalysisExecutionFenced
        logger.info(
            "analysis.job.finished",
            extra={
                "analysis_job_id": str(job.id),
                "dataset_id": str(dataset.id),
                "status": completed_status,
            },
        )
        return {"status": completed_status, **final_summary}
