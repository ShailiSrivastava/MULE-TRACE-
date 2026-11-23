"""Leakage-aware grouped holdouts and a separate ground-truth evaluation API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupShuffleSplit

from app.ml.contracts import AnomalyPrediction, FeatureVector


class EvaluationSplitError(ValueError):
    """A dataset cannot be partitioned into independent groups."""


class EvaluationResult(BaseModel):
    """Held-out metrics; insufficient labels never imply predictive accuracy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["EVALUATED", "INSUFFICIENT_LABELS"]
    method: Literal["GROUPED_HOLDOUT"] = "GROUPED_HOLDOUT"
    labeled_sample_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    precision: float | None = None
    recall: float | None = None
    f1_score: float | None = None
    false_positive_rate: float | None = None
    average_precision: float | None = None
    confusion_matrix: tuple[tuple[int, int], tuple[int, int]] | None = None
    precision_recall_points: tuple[dict[str, float], ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class GroupedHoldout:
    train_vectors: tuple[FeatureVector, ...]
    test_vectors: tuple[FeatureVector, ...]
    train_group_ids: frozenset[UUID]
    test_group_ids: frozenset[UUID]
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]


def grouped_holdout_split(
    vectors: tuple[FeatureVector, ...] | list[FeatureVector],
    *,
    test_size: float = 0.2,
    random_seed: int = 42,
) -> GroupedHoldout:
    """Split by account (or account-component group) before fitting transforms."""

    if not vectors:
        raise EvaluationSplitError("At least one feature vector is required.")
    if not np.isfinite(test_size) or not 0 < test_size < 1:
        raise EvaluationSplitError("test_size must be finite and in (0, 1).")
    group_ids = tuple(vector.group_id or vector.entity_id for vector in vectors)
    unique_groups = set(group_ids)
    if len(unique_groups) < 2:
        raise EvaluationSplitError(
            "At least two independent account groups are required for holdout evaluation."
        )
    splitter = GroupShuffleSplit(
        n_splits=1,
        test_size=test_size,
        random_state=random_seed,
    )
    train, test = next(
        splitter.split(np.zeros((len(vectors), 1)), groups=np.asarray(group_ids, dtype=str))
    )
    train_groups = frozenset(group_ids[index] for index in train)
    test_groups = frozenset(group_ids[index] for index in test)
    if train_groups & test_groups:
        raise RuntimeError("Grouped split leaked evaluation groups into training.")
    return GroupedHoldout(
        train_vectors=tuple(vectors[int(index)] for index in train),
        test_vectors=tuple(vectors[int(index)] for index in test),
        train_group_ids=train_groups,
        test_group_ids=test_groups,
        train_indices=tuple(int(index) for index in train),
        test_indices=tuple(int(index) for index in test),
    )


def evaluate_predictions(
    predictions: tuple[AnomalyPrediction, ...] | list[AnomalyPrediction],
    *,
    ground_truth_by_entity_id: dict[UUID, bool],
    minimum_labeled_samples: int = 10,
) -> EvaluationResult:
    """Calculate metrics only for explicitly labeled held-out predictions.

    ``ground_truth_by_entity_id`` is supplied by the evaluation workflow only;
    feature extraction, preprocessing, model fitting, and inference do not read
    or receive this mapping.
    """

    if minimum_labeled_samples < 2:
        raise ValueError("minimum_labeled_samples must be at least two.")
    entity_types = {prediction.entity_type for prediction in predictions}
    if len(entity_types) > 1:
        raise ValueError("Evaluate one entity type at a time.")
    identifiers = [prediction.entity_id for prediction in predictions]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Evaluation predictions must have unique entity identifiers.")

    labeled = [
        (prediction, ground_truth_by_entity_id[prediction.entity_id])
        for prediction in predictions
        if prediction.entity_id in ground_truth_by_entity_id
    ]
    positives = sum(label is True for _, label in labeled)
    negatives = sum(label is False for _, label in labeled)
    if len(labeled) < minimum_labeled_samples or positives == 0 or negatives == 0:
        return EvaluationResult(
            status="INSUFFICIENT_LABELS",
            labeled_sample_count=len(labeled),
            positive_count=positives,
            negative_count=negatives,
            reason=(
                "Held-out labels are insufficient to establish predictive accuracy; "
                "at least one positive, one negative, and the configured minimum "
                "number of labeled samples are required."
            ),
        )

    y_true = np.asarray([label for _, label in labeled], dtype=np.bool_)
    y_pred = np.asarray(
        [prediction.prediction_label == "ANOMALY" for prediction, _ in labeled],
        dtype=np.bool_,
    )
    y_scores = np.asarray(
        [prediction.normalized_anomaly_score for prediction, _ in labeled],
        dtype=np.float64,
    )
    matrix = confusion_matrix(y_true, y_pred, labels=[False, True])
    true_negative, false_positive, false_negative, true_positive = (
        int(matrix[0, 0]),
        int(matrix[0, 1]),
        int(matrix[1, 0]),
        int(matrix[1, 1]),
    )
    curve_precision, curve_recall, thresholds = precision_recall_curve(
        y_true, y_scores
    )
    curve = tuple(
        {
            "threshold": float(thresholds[index]),
            "precision": float(curve_precision[index + 1]),
            "recall": float(curve_recall[index + 1]),
        }
        for index in range(len(thresholds))
    )
    return EvaluationResult(
        status="EVALUATED",
        labeled_sample_count=len(labeled),
        positive_count=positives,
        negative_count=negatives,
        precision=float(precision_score(y_true, y_pred, zero_division=0)),
        recall=float(recall_score(y_true, y_pred, zero_division=0)),
        f1_score=float(f1_score(y_true, y_pred, zero_division=0)),
        false_positive_rate=float(false_positive / (false_positive + true_negative)),
        average_precision=float(average_precision_score(y_true, y_scores)),
        confusion_matrix=(
            (true_negative, false_positive),
            (false_negative, true_positive),
        ),
        precision_recall_points=curve,
    )
