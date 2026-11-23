"""K-Means cluster assignments and centroid-distance anomaly indicators."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sklearn.cluster import KMeans

from app.ml.models import AnomalyModel, ModelDataError


class KMeansConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str = Field(default="1.0", min_length=1, max_length=40)
    cluster_count: int = Field(default=3, ge=2, le=1_000)
    n_init: int = Field(default=10, ge=1, le=100)
    anomaly_quantile: float = Field(default=0.95, gt=0, le=1)
    random_seed: int = Field(default=42, ge=0)

    @field_validator("anomaly_quantile")
    @classmethod
    def validate_quantile(cls, value: float) -> float:
        if isinstance(value, bool) or not np.isfinite(value):
            raise ValueError("anomaly_quantile must be finite and in (0, 1].")
        return float(value)


class KMeansAnomalyModel(AnomalyModel):
    """Distance is a prioritization indicator, not evidence of wrongdoing."""

    name = "kmeans"

    def __init__(self, config: KMeansConfig | None = None) -> None:
        super().__init__()
        self.config = config or KMeansConfig()
        self.version = self.config.model_version
        self.random_seed = self.config.random_seed
        self.estimator: KMeans | None = None
        self._anomaly_threshold: float | None = None

    @property
    def parameters(self) -> dict[str, Any]:
        return self.config.model_dump(mode="json")

    @property
    def minimum_training_samples(self) -> int:
        return self.config.cluster_count + 1

    def _fit_estimator(self, matrix: np.ndarray) -> None:
        if self.config.cluster_count >= matrix.shape[0]:
            raise ModelDataError(
                "K-Means requires fewer clusters than training samples."
            )
        if np.unique(matrix, axis=0).shape[0] < self.config.cluster_count:
            raise ModelDataError(
                "K-Means requires at least one distinct training vector per cluster."
            )
        self.estimator = KMeans(
            n_clusters=self.config.cluster_count,
            n_init=self.config.n_init,
            random_state=self.config.random_seed,
            algorithm="lloyd",
        )
        self.estimator.fit(matrix)
        distances = self._raw_score_samples(matrix)
        self._anomaly_threshold = float(
            np.quantile(distances, self.config.anomaly_quantile, method="linear")
        )

    def _raw_score_samples(self, matrix: np.ndarray) -> np.ndarray:
        if self.estimator is None:
            raise RuntimeError("K-Means is not fitted.")
        labels = self.estimator.predict(matrix)
        residuals = matrix - self.estimator.cluster_centers_[labels]
        return np.linalg.norm(residuals, axis=1)

    def _labels(self, matrix: np.ndarray) -> tuple[str, ...]:
        if self._anomaly_threshold is None:
            raise RuntimeError("K-Means is not fitted.")
        scores = self._raw_score_samples(matrix)
        return tuple(
            "ANOMALY" if score > self._anomaly_threshold else "NORMAL"
            for score in scores
        )

    def _cluster_ids(self, matrix: np.ndarray) -> tuple[int | None, ...]:
        if self.estimator is None:
            raise RuntimeError("K-Means is not fitted.")
        return tuple(int(cluster) for cluster in self.estimator.predict(matrix))
