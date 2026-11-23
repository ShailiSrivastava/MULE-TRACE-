"""Training and inference orchestration with fit-only-on-training transforms."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.core.model_base import utc_now
from app.graph.models import normalize_utc
from app.ml.contracts import AnomalyPrediction, FeatureVector, ModelRegistryMetadata
from app.ml.evaluation import EvaluationResult
from app.ml.explainability import (
    FeatureBaseline,
    build_feature_baseline,
    explain_feature_deviations,
)
from app.ml.models import AnomalyModel
from app.ml.preprocessing import FeaturePreprocessor, PreprocessorConfig


@dataclass(frozen=True, slots=True)
class FittedAnomalyModel:
    estimator: AnomalyModel
    preprocessor: FeaturePreprocessor
    metadata: ModelRegistryMetadata
    explanation_baseline: FeatureBaseline


def _validate_feature_batch(vectors: tuple[FeatureVector, ...] | list[FeatureVector]) -> None:
    if len(vectors) < 2:
        raise ValueError("At least two feature vectors are required for training.")
    dataset_ids = {vector.dataset_id for vector in vectors}
    entity_types = {vector.entity_type for vector in vectors}
    schema_versions = {vector.feature_schema_version for vector in vectors}
    entity_ids = [vector.entity_id for vector in vectors]
    if len(dataset_ids) != 1:
        raise ValueError("One model fit must reference a single training dataset.")
    if len(entity_types) != 1 or len(schema_versions) != 1:
        raise ValueError("Training vectors must share entity and feature schemas.")
    if len(entity_ids) != len(set(entity_ids)):
        raise ValueError("Training feature vectors must have unique entity IDs.")


def fit_model(
    training_vectors: tuple[FeatureVector, ...] | list[FeatureVector],
    estimator: AnomalyModel,
    *,
    training_timestamp: datetime | None = None,
    preprocessor_config: PreprocessorConfig | None = None,
) -> FittedAnomalyModel:
    """Fit preprocessing and one anomaly model from the supplied training rows."""

    _validate_feature_batch(training_vectors)
    timestamp = normalize_utc(
        training_timestamp or utc_now(), field_name="training_timestamp"
    )
    config = preprocessor_config or PreprocessorConfig(
        feature_schema_version=training_vectors[0].feature_schema_version
    )
    preprocessor = FeaturePreprocessor(config)
    matrix = preprocessor.fit_transform(training_vectors)
    estimator.fit(matrix)
    baseline = build_feature_baseline(training_vectors)
    metadata = ModelRegistryMetadata(
        model_name=estimator.name,
        model_version=estimator.version,
        feature_schema_version=training_vectors[0].feature_schema_version,
        training_dataset_id=training_vectors[0].dataset_id,
        training_timestamp=timestamp,
        training_sample_count=len(training_vectors),
        entity_type=training_vectors[0].entity_type,
        feature_names=preprocessor.output_feature_names,
        model_parameters=estimator.parameters,
        preprocessing_config=preprocessor.config_metadata(),
        random_seed=estimator.random_seed,
        status="TRAINED",
    )
    return FittedAnomalyModel(
        estimator=estimator,
        preprocessor=preprocessor,
        metadata=metadata,
        explanation_baseline=baseline,
    )


def predict(
    fitted: FittedAnomalyModel,
    vectors: tuple[FeatureVector, ...] | list[FeatureVector],
    *,
    analysis_timestamp: datetime | None = None,
    maximum_explanations: int = 3,
) -> tuple[AnomalyPrediction, ...]:
    """Run inference without labels or refitting preprocessing statistics."""

    if not vectors:
        return ()
    analyzed_at = normalize_utc(
        analysis_timestamp or utc_now(), field_name="analysis_timestamp"
    )
    matrix = fitted.preprocessor.transform(vectors)
    scores = fitted.estimator.predict_scores(matrix)
    return tuple(
        AnomalyPrediction(
            dataset_id=vector.dataset_id,
            entity_type=vector.entity_type,
            entity_id=vector.entity_id,
            model_name=fitted.metadata.model_name,
            model_version=fitted.metadata.model_version,
            feature_schema_version=vector.feature_schema_version,
            raw_anomaly_score=scores.raw_scores[index],
            normalized_anomaly_score=scores.normalized_scores[index],
            prediction_label=scores.labels[index],
            cluster_id=scores.cluster_ids[index],
            model_parameters=fitted.metadata.model_parameters,
            feature_values=vector.features,
            as_of=vector.as_of,
            analysis_timestamp=analyzed_at,
            explanations=explain_feature_deviations(
                vector,
                fitted.explanation_baseline,
                maximum_explanations=maximum_explanations,
            ),
            related_account_ids=vector.related_account_ids,
            related_transaction_ids=vector.related_transaction_ids,
        )
        for index, vector in enumerate(vectors)
    )


def attach_evaluation_metadata(
    fitted: FittedAnomalyModel, evaluation: EvaluationResult
) -> FittedAnomalyModel:
    """Attach metrics after a caller evaluates held-out predictions separately."""

    metrics: dict[str, Any] = evaluation.model_dump(mode="json")
    status = "EVALUATED" if evaluation.status == "EVALUATED" else "TRAINED"
    metadata = fitted.metadata.model_copy(
        update={"evaluation_metrics": metrics, "status": status}
    )
    return replace(fitted, metadata=metadata)
