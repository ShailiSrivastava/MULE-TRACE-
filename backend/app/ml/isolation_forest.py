"""Isolation Forest anomaly scoring with reproducible configuration."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sklearn.ensemble import IsolationForest

from app.ml.models import AnomalyModel


class IsolationForestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str = Field(default="1.0", min_length=1, max_length=40)
    n_estimators: int = Field(default=100, ge=10, le=1_000)
    contamination: float | str = 0.1
    max_samples: int | float | str = "auto"
    random_seed: int = Field(default=42, ge=0)

    @field_validator("contamination")
    @classmethod
    def validate_contamination(cls, value: float | str) -> float | str:
        if value == "auto":
            return value
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError("contamination must be 'auto' or a number in (0, 0.5].")
        if not np.isfinite(value) or not 0 < value <= 0.5:
            raise ValueError("contamination must be 'auto' or a number in (0, 0.5].")
        return float(value)

    @field_validator("max_samples")
    @classmethod
    def validate_max_samples(cls, value: float | str) -> int | float | str:
        if value == "auto":
            return value
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError("max_samples must be 'auto', an integer, or a fraction in (0, 1].")
        if not np.isfinite(value) or value <= 0:
            raise ValueError("max_samples must be positive and finite.")
        if isinstance(value, float) and value > 1:
            raise ValueError("Fractional max_samples must be in (0, 1].")
        return value


class IsolationForestModel(AnomalyModel):
    name = "isolation_forest"

    def __init__(self, config: IsolationForestConfig | None = None) -> None:
        super().__init__()
        self.config = config or IsolationForestConfig()
        self.version = self.config.model_version
        self.random_seed = self.config.random_seed
        self.estimator: IsolationForest | None = None

    @property
    def parameters(self) -> dict[str, Any]:
        return self.config.model_dump(mode="json")

    @property
    def minimum_training_samples(self) -> int:
        return 2

    def _fit_estimator(self, matrix: np.ndarray) -> None:
        self.estimator = IsolationForest(
            n_estimators=self.config.n_estimators,
            contamination=self.config.contamination,
            max_samples=self.config.max_samples,
            random_state=self.config.random_seed,
            n_jobs=1,
        )
        self.estimator.fit(matrix)

    def _raw_score_samples(self, matrix: np.ndarray) -> np.ndarray:
        if self.estimator is None:
            raise RuntimeError("Isolation Forest is not fitted.")
        return -self.estimator.score_samples(matrix)

    def _labels(self, matrix: np.ndarray) -> tuple[str, ...]:
        if self.estimator is None:
            raise RuntimeError("Isolation Forest is not fitted.")
        return tuple(
            "ANOMALY" if prediction == -1 else "NORMAL"
            for prediction in self.estimator.predict(matrix)
        )
