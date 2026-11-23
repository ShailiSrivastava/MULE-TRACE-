"""Leakage-aware holdout and ground-truth metric contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.ml.clustering import KMeansAnomalyModel, KMeansConfig
from app.ml.contracts import FeatureVector
from app.ml.evaluation import (
    EvaluationSplitError,
    evaluate_predictions,
    grouped_holdout_split,
)
from app.ml.orchestrator import attach_evaluation_metadata, fit_model, predict


def _vectors(group_count: int = 12):
    dataset_id = uuid4()
    rows = []
    for group in range(group_count):
        group_id = uuid4()
        for within in range(2):
            index = group * 2 + within
            rows.append(
                FeatureVector(
                    dataset_id=dataset_id,
                    entity_type="TRANSACTION",
                    entity_id=uuid4(),
                    feature_schema_version="1.0",
                    as_of=datetime(2026, 10, 1, tzinfo=UTC),
                    features={
                        "historical_count": index,
                        "amount_ratio": Decimal(index + 1) / Decimal(3),
                    },
                    group_id=group_id,
                )
            )
    return tuple(rows)


def test_grouped_split_is_reproducible_and_keeps_account_groups_disjoint():
    vectors = _vectors()
    first = grouped_holdout_split(vectors, test_size=0.25, random_seed=12)
    repeated = grouped_holdout_split(vectors, test_size=0.25, random_seed=12)
    assert first.train_indices == repeated.train_indices
    assert first.test_indices == repeated.test_indices
    assert first.train_group_ids.isdisjoint(first.test_group_ids)
    assert len(first.train_vectors) + len(first.test_vectors) == len(vectors)


def test_evaluation_uses_only_heldout_predictions_and_attaches_metrics():
    vectors = _vectors(14)
    split = grouped_holdout_split(vectors, test_size=0.3, random_seed=9)
    model = KMeansAnomalyModel(
        KMeansConfig(cluster_count=2, anomaly_quantile=0.65, random_seed=2)
    )
    fitted = fit_model(split.train_vectors, model)
    predictions = predict(fitted, split.test_vectors)
    truth = {
        vector.entity_id: index % 2 == 0
        for index, vector in enumerate(vectors)
    }

    result = evaluate_predictions(
        predictions,
        ground_truth_by_entity_id=truth,
        minimum_labeled_samples=4,
    )
    assert result.status == "EVALUATED"
    assert result.labeled_sample_count == len(split.test_vectors)
    assert result.positive_count + result.negative_count == len(split.test_vectors)
    assert result.precision is not None and 0 <= result.precision <= 1
    assert result.recall is not None and 0 <= result.recall <= 1
    assert result.f1_score is not None and 0 <= result.f1_score <= 1
    assert result.false_positive_rate is not None and 0 <= result.false_positive_rate <= 1
    assert result.average_precision is not None
    assert result.confusion_matrix is not None
    assert result.precision_recall_points

    evaluated_model = attach_evaluation_metadata(fitted, result)
    assert evaluated_model.metadata.status == "EVALUATED"
    assert evaluated_model.metadata.evaluation_metrics["labeled_sample_count"] == len(
        split.test_vectors
    )
    assert fitted.metadata.evaluation_metrics is None


def test_insufficient_labels_and_independent_groups_are_reported_explicitly():
    vectors = _vectors(4)
    split = grouped_holdout_split(vectors, test_size=0.5, random_seed=4)
    fitted = fit_model(
        split.train_vectors,
        KMeansAnomalyModel(KMeansConfig(cluster_count=2, random_seed=5)),
    )
    predictions = predict(fitted, split.test_vectors)
    one_label = {predictions[0].entity_id: True}
    result = evaluate_predictions(
        predictions,
        ground_truth_by_entity_id=one_label,
        minimum_labeled_samples=4,
    )
    assert result.status == "INSUFFICIENT_LABELS"
    assert result.precision is None
    assert "insufficient to establish predictive accuracy" in result.reason

    single_group = tuple(
        vector.model_copy(update={"group_id": vectors[0].group_id})
        for vector in vectors[:2]
    )
    try:
        grouped_holdout_split(single_group)
    except EvaluationSplitError as exc:
        assert "independent account groups" in str(exc)
    else:
        raise AssertionError("A single group must never be split across train and evaluation.")
