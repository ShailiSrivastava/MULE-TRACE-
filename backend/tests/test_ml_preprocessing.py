"""Preprocessing schema, missing-value, scaling, and reproducibility tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import numpy as np
import pytest
from pydantic import ValidationError

from app.ml.contracts import FeatureVector
from app.ml.preprocessing import (
    FeaturePreprocessor,
    FeatureSchemaError,
    PreprocessorConfig,
    PreprocessorNotFittedError,
)


def _vector(values, *, index: int, entity_type: str = "ACCOUNT", schema: str = "1.0"):
    return FeatureVector(
        dataset_id=uuid4(),
        entity_type=entity_type,
        entity_id=uuid4(),
        feature_schema_version=schema,
        as_of=datetime(2026, 10, 1, tzinfo=UTC),
        features=values,
        group_id=uuid4(),
    )


def test_median_imputation_scaling_and_constant_features_are_reproducible():
    dataset_id = uuid4()
    vectors = tuple(
        FeatureVector(
            dataset_id=dataset_id,
            entity_type="ACCOUNT",
            entity_id=uuid4(),
            feature_schema_version="1.0",
            as_of=datetime(2026, 10, 1, tzinfo=UTC),
            features={
                "amount_usd": amount,
                "missing_in_training": missing,
                "constant": 7,
            },
            group_id=uuid4(),
        )
        for amount, missing in (
            (Decimal("1.0"), None),
            (Decimal("3.0"), Decimal("2.0")),
            (Decimal("5.0"), Decimal("4.0")),
        )
    )
    config = PreprocessorConfig()
    first = FeaturePreprocessor(config)
    second = FeaturePreprocessor(config)
    first_matrix = first.fit_transform(vectors)
    second_matrix = second.fit_transform(vectors)
    np.testing.assert_allclose(first_matrix, second_matrix)
    assert first_matrix.shape == (3, 6)
    assert first.output_feature_names == (
        "amount_usd",
        "constant",
        "missing_in_training",
        "missing__amount_usd",
        "missing__constant",
        "missing__missing_in_training",
    )
    constant_column = first.output_feature_names.index("constant")
    np.testing.assert_allclose(first_matrix[:, constant_column], 0.0)

    inference = FeatureVector(
        dataset_id=dataset_id,
        entity_type="ACCOUNT",
        entity_id=uuid4(),
        feature_schema_version="1.0",
        as_of=datetime(2026, 10, 2, tzinfo=UTC),
        features={"amount_usd": None, "constant": 7, "missing_in_training": 8},
        group_id=uuid4(),
    )
    means_before = first._scaler.mean_.copy()
    transformed = first.transform([inference])
    assert np.isfinite(transformed).all()
    assert transformed.shape == (1, 6)
    assert transformed[0, first.output_feature_names.index("missing__amount_usd")] == 1
    np.testing.assert_array_equal(first._scaler.mean_, means_before)


def test_preprocessor_requires_fit_and_rejects_unseen_schema_or_fields():
    training = [
        _vector({"count": value}, index=index)
        for index, value in enumerate((1, 2, 3))
    ]
    processor = FeaturePreprocessor()
    with pytest.raises(PreprocessorNotFittedError):
        processor.transform(training)
    processor.fit(training)

    with pytest.raises(FeatureSchemaError, match="schema version"):
        processor.transform([_vector({"count": 4}, index=4, schema="2.0")])
    with pytest.raises(FeatureSchemaError, match="outside the fitted schema"):
        processor.transform([_vector({"count": 4, "new_currency_amount": 5}, index=5)])
    with pytest.raises(FeatureSchemaError, match="entity type"):
        processor.transform([_vector({"count": 4}, index=6, entity_type="TRANSACTION")])


def test_numeric_features_reject_nan_infinity_boolean_and_non_numeric_values():
    base = {
        "dataset_id": uuid4(),
        "entity_type": "ACCOUNT",
        "entity_id": uuid4(),
        "feature_schema_version": "1.0",
        "as_of": datetime(2026, 10, 1, tzinfo=UTC),
    }
    for invalid in (float("nan"), float("inf"), True, "12.4"):
        with pytest.raises(ValidationError):
            FeatureVector(**base, features={"value": invalid})


def test_entirely_missing_training_feature_is_retained_as_finite_input():
    vectors = [_vector({"all_missing": None, "value": index}, index=index) for index in range(1, 4)]
    matrix = FeaturePreprocessor().fit_transform(vectors)
    assert matrix.shape == (3, 4)
    assert np.isfinite(matrix).all()
