"""Controlled conversion of ML anomaly predictions to Phase 9 findings."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal
from uuid import UUID

from app.detection.models import (
    DetectionFinding,
    DetectionRunResult,
    DetectorExecution,
    create_finding,
)
from app.ml.contracts import AnomalyPrediction


def predictions_to_detection_run(
    predictions: tuple[AnomalyPrediction, ...] | list[AnomalyPrediction],
    *,
    dataset_id: UUID,
    anomaly_severity: Literal["info", "low", "medium", "high", "critical"] = "medium",
) -> DetectionRunResult:
    """Build Phase 9-compatible findings for anomalies only.

    Model scores remain evidence fields. This adapter never calls or updates the
    Phase 9 risk-scoring service; callers may pass the result to the existing
    finding-persistence service. Deduplication is stable across repeated runs
    for the same dataset, model version, feature schema, and entity.
    """

    finding_by_key: dict[str, DetectionFinding] = {}
    prediction_by_model: dict[tuple[str, str], list[AnomalyPrediction]] = defaultdict(list)
    for prediction in predictions:
        if prediction.dataset_id != dataset_id:
            raise ValueError("All predictions must belong to the requested dataset.")
        prediction_by_model[(prediction.model_name, prediction.model_version)].append(
            prediction
        )
        if prediction.prediction_label != "ANOMALY":
            continue

        if prediction.entity_type == "ACCOUNT":
            account_ids = tuple(
                set(prediction.related_account_ids) | {prediction.entity_id}
            )
            transaction_ids = prediction.related_transaction_ids
            entity_label = "account"
        else:
            account_ids = prediction.related_account_ids
            transaction_ids = tuple(
                set(prediction.related_transaction_ids) | {prediction.entity_id}
            )
            entity_label = "transaction"

        detector_name = f"ml_{prediction.model_name}"
        evidence: dict[str, Any] = prediction.model_dump(mode="json")
        explanation = (
            "An unsupervised anomaly indicator exceeded the model's configured "
            "decision threshold."
        )
        if prediction.explanations:
            explanation += " " + " ".join(prediction.explanations)
        finding = create_finding(
            detector_name=detector_name,
            detector_version=prediction.model_version,
            category="ml_anomaly",
            severity=anomaly_severity,
            title=f"ML anomaly indicator for {entity_label}",
            explanation=explanation,
            dataset_id=dataset_id,
            account_ids=account_ids,
            transaction_ids=transaction_ids,
            start_at=None,
            end_at=None,
            evidence=evidence,
            parameters={
                "model_name": prediction.model_name,
                "model_version": prediction.model_version,
                "feature_schema_version": prediction.feature_schema_version,
            },
            deduplication_context=(
                prediction.entity_type,
                str(prediction.entity_id),
                prediction.feature_schema_version,
            ),
        )
        previous = finding_by_key.get(finding.deduplication_key)
        if previous is not None and previous != finding:
            raise ValueError("Duplicate ML predictions conflict for one entity/model version.")
        finding_by_key[finding.deduplication_key] = finding

    executions = tuple(
        DetectorExecution(
            detector_name=f"ml_{model_name}",
            detector_version=model_version,
            state="succeeded",
            finding_count=sum(
                finding.detector_name == f"ml_{model_name}"
                and finding.detector_version == model_version
                for finding in finding_by_key.values()
            ),
            statistics={"prediction_count": len(model_predictions)},
        )
        for (model_name, model_version), model_predictions in sorted(
            prediction_by_model.items()
        )
    )
    return DetectionRunResult(
        dataset_id=dataset_id,
        findings=tuple(
            sorted(finding_by_key.values(), key=lambda item: item.deduplication_key)
        ),
        executions=executions,
    )
