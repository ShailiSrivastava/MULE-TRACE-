"""Train-only, schema-checked preprocessing for numeric feature vectors."""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from app.ml.contracts import FeatureVector


class FeatureSchemaError(ValueError):
    """Feature input does not match the fitted preprocessing schema."""


class PreprocessorNotFittedError(RuntimeError):
    """A transform was requested before training-only fit completed."""


class PreprocessorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    missing_strategy: Literal["median"] = "median"
    add_missing_indicators: bool = True
    scale_numeric_features: bool = True
    feature_schema_version: str = Field(default="1.0", min_length=1, max_length=40)


class FeaturePreprocessor:
    """Fit imputation/scaling on training vectors and reuse for inference.

    Constant features remain in the schema; ``StandardScaler`` maps them to
    finite zeros. Entirely missing training columns are retained and imputed
    as zero by scikit-learn's ``keep_empty_features`` behavior.
    """

    def __init__(self, config: PreprocessorConfig | None = None) -> None:
        self.config = config or PreprocessorConfig()
        self._imputer: SimpleImputer | None = None
        self._scaler: StandardScaler | None = None
        self._feature_names: tuple[str, ...] = ()
        self._entity_type: str | None = None
        self._feature_schema_version: str | None = None

    @property
    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    @property
    def output_feature_names(self) -> tuple[str, ...]:
        indicators = (
            tuple(f"missing__{name}" for name in self._feature_names)
            if self.config.add_missing_indicators
            else ()
        )
        return (*self._feature_names, *indicators)

    @property
    def is_fitted(self) -> bool:
        return self._imputer is not None

    def _validate_vectors(self, vectors: tuple[FeatureVector, ...] | list[FeatureVector]) -> None:
        if not vectors:
            raise ValueError("At least one feature vector is required.")
        entity_types = {vector.entity_type for vector in vectors}
        schemas = {vector.feature_schema_version for vector in vectors}
        if len(entity_types) != 1 or len(schemas) != 1:
            raise FeatureSchemaError(
                "One preprocessing batch must use a single entity and feature schema."
            )
        if next(iter(schemas)) != self.config.feature_schema_version:
            raise FeatureSchemaError("Feature schema version does not match configuration.")

    @staticmethod
    def _matrix(
        vectors: tuple[FeatureVector, ...] | list[FeatureVector],
        feature_names: tuple[str, ...],
    ) -> np.ndarray:
        known = set(feature_names)
        rows: list[list[float]] = []
        for vector in vectors:
            extra = set(vector.features) - known
            if extra:
                raise FeatureSchemaError(
                    "Input contains fields outside the fitted schema: "
                    + ", ".join(sorted(extra))
                )
            row: list[float] = []
            for name in feature_names:
                value = vector.features.get(name)
                if value is None:
                    row.append(np.nan)
                else:
                    converted = float(value)
                    if not np.isfinite(converted):
                        raise ValueError("Numeric features must be finite.")
                    row.append(converted)
            rows.append(row)
        matrix = np.asarray(rows, dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[1] == 0:
            raise FeatureSchemaError("At least one numeric feature column is required.")
        return matrix

    def fit(self, training_vectors: tuple[FeatureVector, ...] | list[FeatureVector]) -> FeaturePreprocessor:
        """Learn medians and scaling statistics from training data only."""

        self._validate_vectors(training_vectors)
        names = tuple(sorted({name for vector in training_vectors for name in vector.features}))
        if not names:
            raise FeatureSchemaError("Training features cannot be empty.")
        raw_matrix = self._matrix(training_vectors, names)
        self._imputer = SimpleImputer(
            strategy=self.config.missing_strategy,
            add_indicator=False,
            keep_empty_features=True,
        )
        imputed = self._imputer.fit_transform(raw_matrix)
        if self.config.add_missing_indicators:
            imputed = np.column_stack((imputed, np.isnan(raw_matrix).astype(np.float64)))
        if not np.isfinite(imputed).all():
            raise ValueError("Imputation produced a non-finite value.")
        self._scaler = (
            StandardScaler()
            if self.config.scale_numeric_features
            else None
        )
        if self._scaler is not None:
            scaled = self._scaler.fit_transform(imputed)
            if not np.isfinite(scaled).all():
                raise ValueError("Feature scaling produced a non-finite value.")
        self._feature_names = names
        self._entity_type = training_vectors[0].entity_type
        self._feature_schema_version = training_vectors[0].feature_schema_version
        return self

    def transform(self, vectors: tuple[FeatureVector, ...] | list[FeatureVector]) -> np.ndarray:
        """Transform inference vectors using fitted training statistics only."""

        if self._imputer is None:
            raise PreprocessorNotFittedError("Fit the preprocessor on training data first.")
        self._validate_vectors(vectors)
        if any(vector.entity_type != self._entity_type for vector in vectors):
            raise FeatureSchemaError("Inference entity type differs from the fitted model.")
        if any(vector.feature_schema_version != self._feature_schema_version for vector in vectors):
            raise FeatureSchemaError("Inference feature schema differs from the fitted model.")
        raw_matrix = self._matrix(vectors, self._feature_names)
        imputed = self._imputer.transform(raw_matrix)
        if self.config.add_missing_indicators:
            imputed = np.column_stack((imputed, np.isnan(raw_matrix).astype(np.float64)))
        if not np.isfinite(imputed).all():
            raise ValueError("Imputation produced a non-finite value.")
        if self._scaler is not None:
            imputed = self._scaler.transform(imputed)
        if not np.isfinite(imputed).all():
            raise ValueError("Preprocessing produced a non-finite value.")
        return np.asarray(imputed, dtype=np.float64)

    def fit_transform(
        self, training_vectors: tuple[FeatureVector, ...] | list[FeatureVector]
    ) -> np.ndarray:
        self.fit(training_vectors)
        return self.transform(training_vectors)

    def config_metadata(self) -> dict[str, bool | str]:
        return self.config.model_dump(mode="json")
