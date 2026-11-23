"""Local Outlier Factor with explicit novelty and sample-count validation."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sklearn.neighbors import LocalOutlierFactor

from app.ml.models import AnomalyModel, ModelDataError


class LocalOutlierFactorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str = Field(default="1.0", min_length=1, max_length=40)
    n_neighbors: int = Field(default=20, ge=2, le=1_000)
    contamination: float = 0.1
    novelty: Literal[True] = True
    random_seed: int = Field(default=0, ge=0)

    @field_validator("contamination")
    @classmethod
    def validate_contamination(cls, value: float) -> float:
        if isinstance(value, bool) or not np.isfinite(value) or not 0 < value <= 0.5:
            raise ValueError("contamination must be finite and in (0, 0.5].")
        return float(value)


class LocalOutlierFactorModel(AnomalyModel):
    name = "local_outlier_factor"

    def __init__(self, config: LocalOutlierFactorConfig | None = None) -> None:
        super().__init__()
        self.config = config or LocalOutlierFactorConfig()
        self.version = self.config.model_version
        self.random_seed = self.config.random_seed
        self.estimator: LocalOutlierFactor | None = None

    @property
    def parameters(self) -> dict[str, Any]:
        return self.config.model_dump(mode="json")

    @property
    def minimum_training_samples(self) -> int:
        return self.config.n_neighbors + 1

    def _fit_estimator(self, matrix: np.ndarray) -> None:
        if self.config.n_neighbors >= matrix.shape[0]:
            raise ModelDataError(
                "LOF requires n_neighbors to be smaller than the training sample count."
            )
        self.estimator = LocalOutlierFactor(
            n_neighbors=self.config.n_neighbors,
            contamination=self.config.contamination,
            novelty=True,
            n_jobs=1,
        )
        self.estimator.fit(matrix)

    def _raw_score_samples(self, matrix: np.ndarray) -> np.ndarray:
        if self.estimator is None:
            raise RuntimeError("Local Outlier Factor is not fitted.")
        return -self.estimator.score_samples(matrix)

    def _labels(self, matrix: np.ndarray) -> tuple[str, ...]:
        if self.estimator is None:
            raise RuntimeError("Local Outlier Factor is not fitted.")
        return tuple(
            "ANOMALY" if prediction == -1 else "NORMAL"
            for prediction in self.estimator.predict(matrix)
        )
