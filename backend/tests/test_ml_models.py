"""Isolation Forest, LOF, K-Means, and model-contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import numpy as np
import pytest
from pydantic import ValidationError

from app.ml.clustering import KMeansAnomalyModel, KMeansConfig
from app.ml.contracts import FeatureVector
from app.ml.isolation_forest import IsolationForestConfig, IsolationForestModel
from app.ml.local_outlier_factor import (
    LocalOutlierFactorConfig,
    LocalOutlierFactorModel,
)
from app.ml.models import ModelDataError
from app.ml.orchestrator import fit_model, predict


def _vectors(values: list[tuple[float, float]], *, dataset_id=None):
    dataset_id = dataset_id or uuid4()
    return tuple(
        FeatureVector(
            dataset_id=dataset_id,
            entity_type="ACCOUNT",
            entity_id=uuid4(),
            feature_schema_version="1.0",
            as_of=datetime(2026, 10, 1, tzinfo=UTC),
            features={"activity": Decimal(str(x)), "counterparties": Decimal(str(y))},
            group_id=uuid4(),
        )
        for x, y in values
    )


def test_isolation_forest_training_inference_and_seed_determinism():
    train = _vectors([(float(value), float(value % 4)) for value in range(20)])
    anomaly = _vectors([(100.0, 100.0)], dataset_id=train[0].dataset_id)
    config = IsolationForestConfig(
        model_version="if-2026-01", n_estimators=50, contamination=0.1, random_seed=9
    )
    first = fit_model(train, IsolationForestModel(config))
    second = fit_model(train, IsolationForestModel(config))
    first_result = predict(first, anomaly)
    second_result = predict(second, anomaly)

    assert first.metadata.model_name == "isolation_forest"
    assert first.metadata.model_parameters["random_seed"] == 9
    assert first_result[0].prediction_label == "ANOMALY"
    assert first_result[0].score_type == "ANOMALY_SCORE"
    assert first_result[0].normalized_anomaly_score == second_result[0].normalized_anomaly_score
    assert first_result[0].cluster_id is None
    assert first_result[0].explanations


def test_lof_novelty_inference_and_neighbor_constraints():
    train = _vectors(
        [(float(index % 3), float((index // 3) % 3)) for index in range(12)]
    )
    test = _vectors([(30.0, 30.0)], dataset_id=train[0].dataset_id)
    model = LocalOutlierFactorModel(
        LocalOutlierFactorConfig(model_version="lof-2026-01", n_neighbors=3)
    )
    fitted = fit_model(train, model)
    result = predict(fitted, test)
    assert result[0].prediction_label == "ANOMALY"
    assert model.config.novelty is True

    with pytest.raises(ModelDataError, match="at least 4 training samples"):
        fit_model(
            train[:3],
            LocalOutlierFactorModel(LocalOutlierFactorConfig(n_neighbors=3)),
        )


def test_kmeans_assignments_distances_and_seed_determinism():
    values = [
        (float(index) / 10, float(index % 2) / 10) for index in range(8)
    ] + [(10 + float(index) / 10, 10 + float(index % 2) / 10) for index in range(8)]
    train = _vectors(values)
    test = _vectors([(100.0, 100.0)], dataset_id=train[0].dataset_id)
    config = KMeansConfig(
        model_version="kmeans-2026-01",
        cluster_count=2,
        anomaly_quantile=0.8,
        random_seed=4,
    )
    first = fit_model(train, KMeansAnomalyModel(config))
    second = fit_model(train, KMeansAnomalyModel(config))
    result = predict(first, test)[0]
    repeated = predict(second, test)[0]
    assert result.cluster_id in {0, 1}
    assert result.prediction_label == "ANOMALY"
    assert result.raw_anomaly_score == repeated.raw_anomaly_score
    assert result.model_name == "kmeans"


def test_empty_small_nonfinite_and_invalid_configuration_cases():
    with pytest.raises(ValueError, match="At least two"):
        fit_model([], IsolationForestModel())
    with pytest.raises(ValidationError):
        IsolationForestConfig(contamination=0.0)
    with pytest.raises(ValidationError):
        LocalOutlierFactorConfig(n_neighbors=1)
    with pytest.raises(ValidationError):
        KMeansConfig(cluster_count=1)

    too_small_for_clusters = _vectors([(1.0, 1.0), (2.0, 2.0)])
    with pytest.raises(ModelDataError, match="at least 3 training samples"):
        fit_model(
            too_small_for_clusters,
            KMeansAnomalyModel(KMeansConfig(cluster_count=2)),
        )

    duplicate_vectors = _vectors(
        [(1.0, 1.0), (1.0, 1.0), (2.0, 2.0), (2.0, 2.0)]
    )
    with pytest.raises(ModelDataError, match="one distinct training vector per cluster"):
        fit_model(
            duplicate_vectors,
            KMeansAnomalyModel(KMeansConfig(cluster_count=3)),
        )

    model = IsolationForestModel()
    with pytest.raises(ModelDataError, match="NaN or infinite"):
        model.fit(np.asarray([[1.0, np.inf], [2.0, 3.0]]))


def test_fit_rejects_mixed_training_datasets_and_feature_schemas():
    first = _vectors([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)])
    other_dataset = _vectors([(4.0, 4.0)], dataset_id=uuid4())
    with pytest.raises(ValueError, match="single training dataset"):
        fit_model((*first, *other_dataset), IsolationForestModel())
