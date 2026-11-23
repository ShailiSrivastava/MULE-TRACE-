"""Process-local fitted estimators with immutable version keys.

Durable registry metadata is written through ``services.ml_registry``. Fitted
scikit-learn objects are deliberately process-local; no pickle/joblib artifacts
are created or loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from app.ml.contracts import ModelRegistryMetadata
from app.ml.explainability import FeatureBaseline


class ModelVersionConflict(RuntimeError):
    """A model name/version key is already registered and cannot be replaced."""


class FittedModelUnavailable(LookupError):
    """Registry metadata exists but its process-local estimator is not loaded."""


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    metadata: ModelRegistryMetadata
    estimator: Any
    preprocessor: Any
    explanation_baseline: FeatureBaseline


class ModelRegistry:
    """Thread-safe in-memory access to estimators for the current process."""

    def __init__(self) -> None:
        self._models: dict[tuple[str, str], RegisteredModel] = {}
        self._lock = RLock()

    def register(
        self,
        *,
        metadata: ModelRegistryMetadata,
        estimator: Any,
        preprocessor: Any,
        explanation_baseline: FeatureBaseline,
    ) -> RegisteredModel:
        key = (metadata.model_name, metadata.model_version)
        with self._lock:
            if key in self._models:
                raise ModelVersionConflict(
                    f"Model version {metadata.model_name}:{metadata.model_version} already exists."
                )
            registered = RegisteredModel(
                metadata=metadata,
                estimator=estimator,
                preprocessor=preprocessor,
                explanation_baseline=explanation_baseline,
            )
            self._models[key] = registered
            return registered

    def get(self, model_name: str, model_version: str) -> RegisteredModel:
        with self._lock:
            try:
                return self._models[(model_name, model_version)]
            except KeyError as exc:
                raise FittedModelUnavailable(
                    "Fitted model is not present in this process."
                ) from exc

    def metadata(self) -> tuple[ModelRegistryMetadata, ...]:
        with self._lock:
            return tuple(
                item.metadata
                for _, item in sorted(self._models.items(), key=lambda pair: pair[0])
            )
