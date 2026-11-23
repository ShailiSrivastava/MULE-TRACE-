"""Model interfaces and numerical validation shared by sklearn estimators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np


class ModelDataError(ValueError):
    """Training or inference data violates a model's numerical requirements."""


@dataclass(frozen=True, slots=True)
class ModelScores:
    raw_scores: tuple[float, ...]
    normalized_scores: tuple[float, ...]
    labels: tuple[str, ...]
    cluster_ids: tuple[int | None, ...]


def validated_matrix(values: np.ndarray, *, minimum_samples: int) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise ModelDataError("Model input must be a nonempty two-dimensional matrix.")
    if matrix.shape[0] < minimum_samples:
        raise ModelDataError(
            f"Model requires at least {minimum_samples} training samples."
        )
    if not np.isfinite(matrix).all():
        raise ModelDataError("Model input contains NaN or infinite values.")
    return matrix


class AnomalyModel(ABC):
    """Common interface for deterministic unsupervised anomaly estimators."""

    name: str
    version: str
    random_seed: int

    def __init__(self) -> None:
        self._raw_min: float | None = None
        self._raw_max: float | None = None
        self._fitted = False

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """Return JSON-ready immutable model configuration."""

    @property
    @abstractmethod
    def minimum_training_samples(self) -> int:
        """Return this estimator's explicit minimum training sample count."""

    @abstractmethod
    def _fit_estimator(self, matrix: np.ndarray) -> None:
        """Fit the concrete estimator."""

    @abstractmethod
    def _raw_score_samples(self, matrix: np.ndarray) -> np.ndarray:
        """Return raw scores with larger values meaning more anomalous."""

    @abstractmethod
    def _labels(self, matrix: np.ndarray) -> tuple[str, ...]:
        """Return labels from the algorithm's configured decision rule."""

    def _cluster_ids(self, matrix: np.ndarray) -> tuple[int | None, ...]:
        return tuple(None for _ in range(matrix.shape[0]))

    def fit(self, matrix: np.ndarray) -> AnomalyModel:
        training = validated_matrix(
            matrix, minimum_samples=self.minimum_training_samples
        )
        self._fit_estimator(training)
        training_scores = np.asarray(self._raw_score_samples(training), dtype=np.float64)
        if training_scores.shape != (training.shape[0],) or not np.isfinite(
            training_scores
        ).all():
            raise ModelDataError("Estimator produced invalid training anomaly scores.")
        if (training_scores < 0).any():
            raise ModelDataError("Raw anomaly scores must be nonnegative.")
        self._raw_min = float(training_scores.min())
        self._raw_max = float(training_scores.max())
        self._fitted = True
        return self

    def predict_scores(self, matrix: np.ndarray) -> ModelScores:
        if not self._fitted or self._raw_min is None or self._raw_max is None:
            raise RuntimeError("Fit the anomaly model before inference.")
        values = validated_matrix(matrix, minimum_samples=1)
        raw = np.asarray(self._raw_score_samples(values), dtype=np.float64)
        labels = self._labels(values)
        cluster_ids = self._cluster_ids(values)
        if raw.shape != (values.shape[0],) or not np.isfinite(raw).all():
            raise ModelDataError("Estimator produced invalid inference anomaly scores.")
        if (
            (raw < 0).any()
            or len(labels) != values.shape[0]
            or len(cluster_ids) != values.shape[0]
        ):
            raise ModelDataError("Estimator produced invalid prediction values.")
        spread = self._raw_max - self._raw_min
        if spread <= np.finfo(np.float64).eps:
            normalized = np.zeros_like(raw)
        else:
            normalized = np.clip((raw - self._raw_min) / spread, 0.0, 1.0)
        return ModelScores(
            raw_scores=tuple(float(value) for value in raw),
            normalized_scores=tuple(float(value) for value in normalized),
            labels=labels,
            cluster_ids=cluster_ids,
        )
