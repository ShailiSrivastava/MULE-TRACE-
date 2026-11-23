"""Registry persistence, explicit labels, and Phase 9 ML adapter tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.model_base import Base
from app.detection.models import DetectionRunResult, create_finding
from app.ml.contracts import AnomalyPrediction, FeatureVector, ModelRegistryMetadata
from app.ml.isolation_forest import IsolationForestConfig, IsolationForestModel
from app.ml.orchestrator import fit_model
from app.ml.phase9_adapter import predictions_to_detection_run
from app.ml.registry import ModelRegistry, ModelVersionConflict
from app.models import (
    Account,
    AnalysisJob,
    AuditLog,
    Dataset,
    DetectionFinding,
    FindingObservation,
    GroundTruthLabel,
    RiskAssessment,
    Transaction,
    User,
    UserRole,
)
from app.services.dataset_access import DatasetScopeNotFound
from app.services.findings import persist_detection_run
from app.services.ml_evaluation import (
    GroundTruthConfigurationError,
    load_binary_ground_truth,
)
from app.services.ml_features import extract_owned_dataset_features
from app.services.ml_registry import ModelRegistryConflict, persist_model_metadata


@pytest.fixture
def ml_db() -> Generator[dict, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(
            email=f"ml-owner-{uuid4().hex}@example.com",
            password_hash="hash",
            role=UserRole.INVESTIGATOR.value,
        )
        other_owner = User(
            email=f"ml-other-{uuid4().hex}@example.com", password_hash="hash"
        )
        db.add_all([owner, other_owner])
        db.flush()
        dataset = Dataset(owner_id=owner.id, name=f"ML {uuid4().hex}")
        other_dataset = Dataset(owner_id=other_owner.id, name=f"Other ML {uuid4().hex}")
        db.add_all([dataset, other_dataset])
        db.flush()
        accounts = [
            Account(dataset_id=dataset.id, external_id=f"ml-account-{uuid4().hex}")
            for _ in range(3)
        ]
        db.add_all(accounts)
        db.flush()
        transactions = [
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[0].id,
                receiver_account_id=accounts[1].id,
                amount=Decimal("10.250000"),
                currency="USD",
                occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
            ),
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[1].id,
                receiver_account_id=accounts[2].id,
                amount=Decimal("125.000000"),
                currency="USD",
                occurred_at=datetime(2026, 10, 2, tzinfo=UTC),
            ),
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[2].id,
                receiver_account_id=accounts[0].id,
                amount=Decimal("80.000000"),
                currency="EUR",
                occurred_at=datetime(2026, 10, 3, tzinfo=UTC),
            ),
        ]
        job = AnalysisJob(dataset_id=dataset.id, job_type="detection")
        db.add_all([*transactions, job])
        db.flush()
        labels = [
            GroundTruthLabel(
                dataset_id=dataset.id,
                transaction_id=transactions[0].id,
                label_code="mule",
                label_scheme="curated_v1",
                source="curated",
            ),
            GroundTruthLabel(
                dataset_id=dataset.id,
                transaction_id=transactions[1].id,
                label_code="normal",
                label_scheme="curated_v1",
                source="curated",
            ),
            GroundTruthLabel(
                dataset_id=dataset.id,
                transaction_id=transactions[2].id,
                label_code="review",
                label_scheme="curated_v1",
                source="curated",
            ),
        ]
        db.add_all(labels)
        db.commit()
        for item in [owner, other_owner, dataset, other_dataset, *accounts, *transactions, job]:
            db.refresh(item)
        yield {
            "engine": engine,
            "factory": factory,
            "owner": owner,
            "other_owner": other_owner,
            "dataset": dataset,
            "other_dataset": other_dataset,
            "accounts": accounts,
            "transactions": transactions,
            "job": job,
        }
    engine.dispose()


def _registry_metadata(dataset_id, *, model_version="iforest-test-1"):
    return ModelRegistryMetadata(
        model_name="isolation_forest",
        model_version=model_version,
        feature_schema_version="1.0",
        training_dataset_id=dataset_id,
        training_timestamp=datetime(2026, 10, 10, 12, tzinfo=UTC),
        training_sample_count=10,
        entity_type="ACCOUNT",
        feature_names=("outgoing_count", "outgoing_sum_usd"),
        model_parameters={"n_estimators": 100, "random_seed": 42},
        preprocessing_config={"scaler": "standard"},
        random_seed=42,
    )


def test_process_registry_keeps_immutable_model_version_keys():
    dataset_id = uuid4()
    vectors = tuple(
        FeatureVector(
            dataset_id=dataset_id,
            entity_type="ACCOUNT",
            entity_id=uuid4(),
            feature_schema_version="1.0",
            as_of=datetime(2026, 10, 10, tzinfo=UTC),
            features={"transaction_count": index, "usd_sum": index * 3},
            group_id=uuid4(),
        )
        for index in range(6)
    )
    fitted = fit_model(
        vectors,
        IsolationForestModel(
            IsolationForestConfig(model_version="registry-test", random_seed=7)
        ),
    )
    registry = ModelRegistry()
    first = registry.register(
        metadata=fitted.metadata,
        estimator=fitted.estimator,
        preprocessor=fitted.preprocessor,
        explanation_baseline=fitted.explanation_baseline,
    )

    assert registry.get("isolation_forest", "registry-test") is first
    assert registry.metadata() == (fitted.metadata,)
    with pytest.raises(ModelVersionConflict):
        registry.register(
            metadata=fitted.metadata,
            estimator=fitted.estimator,
            preprocessor=fitted.preprocessor,
            explanation_baseline=fitted.explanation_baseline,
        )


def test_registry_metadata_is_owner_scoped_immutable_and_audited(ml_db):
    context = ml_db
    with context["factory"]() as db:
        metadata = _registry_metadata(context["dataset"].id)
        record = persist_model_metadata(db, actor=context["owner"], metadata=metadata)

        assert record.model_name == metadata.model_name
        assert record.feature_names == list(metadata.feature_names)
        assert record.training_sample_count == 10
        assert record.training_timestamp == metadata.training_timestamp
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == record.id,
                AuditLog.event_type == "ml.model.registered",
            )
        )
        assert audit is not None
        assert audit.details["training_sample_count"] == 10

        with pytest.raises(ModelRegistryConflict):
            persist_model_metadata(db, actor=context["owner"], metadata=metadata)
        conflicting_metadata = metadata.model_copy(
            update={"model_parameters": {"n_estimators": 5}}
        )
        with pytest.raises(ModelRegistryConflict):
            persist_model_metadata(
                db, actor=context["owner"], metadata=conflicting_metadata
            )
        assert db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.event_type == "ml.model.registered"
        )) == 1

        foreign_metadata = _registry_metadata(
            context["other_dataset"].id, model_version="iforest-test-2"
        )
        with pytest.raises(DatasetScopeNotFound):
            persist_model_metadata(
                db, actor=context["owner"], metadata=foreign_metadata
            )


def test_ground_truth_loader_uses_explicit_binary_codes_and_ignores_unknowns(ml_db):
    context = ml_db
    with context["factory"]() as db:
        labels = load_binary_ground_truth(
            db,
            dataset_id=context["dataset"].id,
            actor=context["owner"],
            label_scheme="curated_v1",
            positive_label_codes={"MULE"},
            negative_label_codes={"normal"},
        )

        assert labels == {
            context["transactions"][0].id: True,
            context["transactions"][1].id: False,
        }
        assert context["transactions"][2].id not in labels

        with pytest.raises(GroundTruthConfigurationError):
            load_binary_ground_truth(
                db,
                dataset_id=context["dataset"].id,
                actor=context["owner"],
                label_scheme="curated_v1",
                positive_label_codes={"mule"},
                negative_label_codes={"mule"},
            )


def test_feature_service_is_owner_scoped_and_cutoff_limited(ml_db):
    context = ml_db
    with context["factory"]() as db:
        batch = extract_owned_dataset_features(
            db,
            dataset_id=context["dataset"].id,
            owner_id=context["owner"].id,
            analysis_cutoff=datetime(2026, 10, 2, tzinfo=UTC),
        )
        assert {row.entity_id for row in batch.transaction_features} == {
            context["transactions"][0].id,
            context["transactions"][1].id,
        }
        assert all(
            not any("label" in name.lower() for name in row.features)
            for row in (*batch.account_features, *batch.transaction_features)
        )
        with pytest.raises(DatasetScopeNotFound):
            extract_owned_dataset_features(
                db,
                dataset_id=context["dataset"].id,
                owner_id=context["other_owner"].id,
                analysis_cutoff=datetime(2026, 10, 2, tzinfo=UTC),
            )


def _prediction(context, *, entity_id, label="ANOMALY"):
    transaction = context["transactions"][0]
    return AnomalyPrediction(
        dataset_id=context["dataset"].id,
        entity_type="TRANSACTION",
        entity_id=entity_id,
        model_name="isolation_forest",
        model_version="iforest-test-1",
        feature_schema_version="1.0",
        raw_anomaly_score=1.25,
        normalized_anomaly_score=0.94,
        prediction_label=label,
        model_parameters={"n_estimators": 100},
        feature_values={"amount_usd": Decimal("10.250000")},
        as_of=datetime(2026, 10, 1, tzinfo=UTC),
        analysis_timestamp=datetime(2026, 10, 10, 12, tzinfo=UTC),
        explanations=("amount_usd is well above its training baseline",),
        related_account_ids=(
            transaction.sender_account_id,
            transaction.receiver_account_id,
        ),
        related_transaction_ids=(transaction.id,),
    )


def test_phase9_adapter_deduplicates_and_persists_without_touching_risk_scores(ml_db):
    context = ml_db
    anomalous = _prediction(context, entity_id=context["transactions"][0].id)
    normal = _prediction(
        context,
        entity_id=context["transactions"][1].id,
        label="NORMAL",
    )
    adapted = predictions_to_detection_run(
        (anomalous, anomalous, normal), dataset_id=context["dataset"].id
    )
    assert len(adapted.findings) == 1
    assert adapted.executions[0].finding_count == 1
    assert adapted.findings[0].category == "ml_anomaly"

    rule_finding = create_finding(
        detector_name="multi_hop",
        detector_version="1.0",
        category="multi_hop_movement",
        severity="high",
        title="Rule based pattern",
        explanation="Existing Phase 8 finding remains distinct.",
        dataset_id=context["dataset"].id,
        account_ids=(context["accounts"][0].id, context["accounts"][1].id),
        transaction_ids=(context["transactions"][0].id,),
        start_at=None,
        end_at=None,
        evidence={"source": "rule"},
        parameters={"maximum_hops": 4},
    )
    combined = DetectionRunResult(
        dataset_id=context["dataset"].id,
        findings=(*adapted.findings, rule_finding),
        executions=adapted.executions,
    )

    with context["factory"]() as db:
        persisted = persist_detection_run(
            db,
            dataset_id=context["dataset"].id,
            analysis_job_id=context["job"].id,
            actor=context["owner"],
            result=combined,
            observed_at=datetime(2026, 10, 10, 12, tzinfo=UTC),
        )
        repeated = persist_detection_run(
            db,
            dataset_id=context["dataset"].id,
            analysis_job_id=context["job"].id,
            actor=context["owner"],
            result=combined,
            observed_at=datetime(2026, 10, 11, 12, tzinfo=UTC),
        )
        assert persisted.created_count == 2
        assert repeated.unchanged_count == 2
        assert db.scalar(select(func.count()).select_from(DetectionFinding)) == 2
        assert db.scalar(select(func.count()).select_from(FindingObservation)) == 2
        assert db.scalar(select(func.count()).select_from(RiskAssessment)) == 0
        categories = set(db.scalars(select(DetectionFinding.category)).all())
        assert categories == {"ml_anomaly", "multi_hop_movement"}
