"""HTTP tests for the Phase 12 graph and analytics read APIs."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db, get_engine
from app.core.model_base import Base
from app.detection.models import DetectionRunResult, create_finding
from app.main import app
from app.models import (
    Account,
    AnalysisJob,
    Dataset,
    MLModelRegistryRecord,
    RiskAssessment,
    Transaction,
    User,
    UserRole,
)
from app.security.tokens import create_access_token
from app.services.findings import persist_detection_run

TEST_JWT_SECRET = "phase-twelve-test-secret-value-at-least-32-bytes"
BASE_TIME = datetime(2026, 11, 20, 12, tzinfo=UTC)


@pytest.fixture
def graph_analytics_api(monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
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

    def override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(TEST_JWT_SECRET))

    owner = User(
        email=f"phase12-owner-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.INVESTIGATOR.value,
    )
    other_owner = User(
        email=f"phase12-other-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.ANALYST.value,
    )
    with factory() as db:
        db.add_all([owner, other_owner])
        db.flush()
        dataset = Dataset(owner_id=owner.id, name=f"Graph {uuid4().hex}", status="ready")
        empty_dataset = Dataset(
            owner_id=owner.id, name=f"Empty {uuid4().hex}", status="ready"
        )
        other_dataset = Dataset(
            owner_id=other_owner.id, name=f"Other {uuid4().hex}", status="ready"
        )
        db.add_all([dataset, empty_dataset, other_dataset])
        db.flush()
        accounts = [
            Account(
                dataset_id=dataset.id,
                external_id=f"private-ext-{index}-{uuid4().hex}",
                account_type="business" if index == 0 else "personal",
                institution_code="BANK-A",
                country_code="US" if index != 2 else "GB",
            )
            for index in range(4)
        ]
        other_account = Account(
            dataset_id=other_dataset.id,
            external_id=f"other-{uuid4().hex}",
        )
        db.add_all([*accounts, other_account])
        db.flush()
        transactions = [
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[0].id,
                receiver_account_id=accounts[1].id,
                amount=Decimal("10.123456"),
                currency="USD",
                occurred_at=BASE_TIME,
                transaction_type="transfer",
                channel="online",
                status="settled",
            ),
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[0].id,
                receiver_account_id=accounts[1].id,
                amount=Decimal("20.000001"),
                currency="USD",
                occurred_at=BASE_TIME + timedelta(minutes=1),
                transaction_type="transfer",
                channel="online",
                status="settled",
            ),
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[1].id,
                receiver_account_id=accounts[2].id,
                amount=Decimal("7.250000"),
                currency="EUR",
                occurred_at=BASE_TIME + timedelta(minutes=2),
            ),
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[2].id,
                receiver_account_id=accounts[0].id,
                amount=Decimal("3.000000"),
                currency="USD",
                occurred_at=BASE_TIME + timedelta(minutes=3),
            ),
        ]
        job = AnalysisJob(
            dataset_id=dataset.id,
            created_by_id=owner.id,
            job_type="analysis",
            status="completed",
            progress_percent=100,
            current_stage="complete",
            result_summary={"account_count": 4, "transaction_count": 4},
            started_at=BASE_TIME,
            finished_at=BASE_TIME + timedelta(minutes=4),
        )
        db.add_all([*transactions, job])
        db.flush()
        risk = RiskAssessment(
            dataset_id=dataset.id,
            analysis_job_id=job.id,
            account_id=accounts[0].id,
            score=Decimal("0.750000"),
            risk_level="high",
            scoring_model_version="test-risk-1",
            score_components={"findings": []},
            rationale={"source": "test fixture"},
            assessed_at=BASE_TIME + timedelta(minutes=5),
        )
        ml_model = MLModelRegistryRecord(
            model_name="isolation_forest",
            model_version="test-1",
            feature_schema_version="account-v1",
            entity_type="ACCOUNT",
            training_dataset_id=dataset.id,
            training_timestamp=BASE_TIME,
            training_sample_count=4,
            feature_names=["in_degree", "out_degree"],
            model_parameters={"contamination": "0.05"},
            preprocessing_config={"scaler": "standard"},
            evaluation_metrics=None,
            random_seed=17,
            status="TRAINED",
            created_by_id=owner.id,
        )
        db.add_all([risk, ml_model])
        db.flush()

        anomaly = create_finding(
            detector_name="ml_isolation_forest",
            detector_version="test-1",
            category="ml_anomaly",
            severity="high",
            title="Account anomaly",
            explanation="Persisted anomaly evidence from the fixture.",
            dataset_id=dataset.id,
            account_ids=(accounts[0].id, accounts[1].id),
            transaction_ids=(transactions[0].id,),
            start_at=transactions[0].occurred_at,
            end_at=transactions[0].occurred_at,
            evidence={"model_score": "0.875000", "prediction_label": "ANOMALY"},
            parameters={"model_name": "isolation_forest", "model_version": "test-1"},
            deduplication_context=("phase12-anomaly", uuid4().hex),
        )
        persisted = persist_detection_run(
            db,
            dataset_id=dataset.id,
            analysis_job_id=job.id,
            actor=owner,
            result=DetectionRunResult(
                dataset_id=dataset.id,
                findings=(anomaly,),
                executions=(),
            ),
            observed_at=BASE_TIME + timedelta(minutes=6),
        )
        finding_id = persisted.findings[0].id
        db.commit()
        for entity in [
            owner,
            other_owner,
            dataset,
            empty_dataset,
            other_dataset,
            *accounts,
            other_account,
            *transactions,
            job,
            risk,
            ml_model,
        ]:
            db.refresh(entity)

    with TestClient(app) as client:
        yield {
            "client": client,
            "owner": owner,
            "other_owner": other_owner,
            "dataset": dataset,
            "empty_dataset": empty_dataset,
            "other_dataset": other_dataset,
            "accounts": accounts,
            "other_account": other_account,
            "transactions": transactions,
            "job": job,
            "finding_id": finding_id,
            "owner_headers": {
                "Authorization": f"Bearer {create_access_token(owner.id)}"
            },
            "other_headers": {
                "Authorization": f"Bearer {create_access_token(other_owner.id)}"
            },
        }
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _dataset_path(dataset_id: UUID, suffix: str) -> str:
    return f"/api/v1/datasets/{dataset_id}/{suffix}"


def test_graph_overview_nodes_edges_filters_and_parallel_transactions(graph_analytics_api):
    context = graph_analytics_api
    client = context["client"]
    dataset_id = context["dataset"].id

    assert client.get(_dataset_path(dataset_id, "graph/overview")).status_code == 401
    overview = client.get(
        _dataset_path(dataset_id, "graph/overview"), headers=context["owner_headers"]
    )
    assert overview.status_code == 200
    body = overview.json()
    assert body["node_count"] == 4
    assert body["edge_count"] == 4
    assert body["directed_density"] == pytest.approx(0.25)
    assert body["currency_totals"] == [
        {"currency": "EUR", "transaction_count": 1, "total_amount": "7.250000"},
        {"currency": "USD", "transaction_count": 3, "total_amount": "33.123457"},
    ]

    nodes = client.get(
        _dataset_path(dataset_id, "graph/nodes"),
        params={"page": 1, "page_size": 2, "country_code": "us"},
        headers=context["owner_headers"],
    )
    assert nodes.status_code == 200
    assert nodes.json()["total"] == 3
    assert len(nodes.json()["items"]) == 2
    assert "external_id" not in nodes.text
    assert nodes.json()["items"][0]["data"]["id"]

    edges = client.get(
        _dataset_path(dataset_id, "graph/edges"),
        params={"currency": "usd", "minimum_amount": "10", "maximum_amount": "21"},
        headers=context["owner_headers"],
    )
    assert edges.status_code == 200
    edge_items = edges.json()["items"]
    assert edges.json()["total"] == 2
    assert len({item["data"]["id"] for item in edge_items}) == 2
    assert {item["data"]["source"] for item in edge_items} == {
        str(context["accounts"][0].id)
    }
    assert {item["data"]["target"] for item in edge_items} == {
        str(context["accounts"][1].id)
    }
    for item in edge_items:
        assert Decimal(item["data"]["amount"]) in {
            Decimal("10.123456"),
            Decimal("20.000001"),
        }
        assert datetime.fromisoformat(item["data"]["occurred_at"]).utcoffset() == UTC.utcoffset(BASE_TIME)

    invalid_window = client.get(
        _dataset_path(dataset_id, "graph/edges"),
        params={
            "start_at": BASE_TIME.isoformat(),
            "end_at": BASE_TIME.isoformat(),
        },
        headers=context["owner_headers"],
    )
    assert invalid_window.status_code == 422


def test_account_network_neighborhood_and_bounded_paths(graph_analytics_api):
    context = graph_analytics_api
    client = context["client"]
    dataset_id = context["dataset"].id
    account_id = context["accounts"][0].id

    network = client.get(
        _dataset_path(dataset_id, f"accounts/{account_id}/network"),
        headers=context["owner_headers"],
    )
    assert network.status_code == 200
    body = network.json()
    assert body["in_degree"] == 1
    assert body["out_degree"] == 2
    assert body["total_transaction_count"] == 3
    assert body["total_unique_counterparty_count"] == 2
    assert body["outgoing_amount_by_currency"] == {"USD": "30.123457"}

    outgoing = client.get(
        _dataset_path(dataset_id, f"accounts/{account_id}/neighborhood"),
        params={"depth": 1, "direction": "outgoing"},
        headers=context["owner_headers"],
    )
    assert outgoing.status_code == 200
    assert outgoing.json()["node_count"] == 2
    assert outgoing.json()["edge_count"] == 2

    neighborhood = client.get(
        _dataset_path(dataset_id, f"accounts/{account_id}/neighborhood"),
        params={"depth": 1, "direction": "both"},
        headers=context["owner_headers"],
    )
    assert neighborhood.status_code == 200
    assert neighborhood.json()["node_count"] == 3
    assert neighborhood.json()["edge_count"] == 4

    target_id = context["accounts"][2].id
    paths = client.get(
        _dataset_path(dataset_id, "graph/paths"),
        params={
            "source_account_id": account_id,
            "target_account_id": target_id,
            "max_hops": 2,
        },
        headers=context["owner_headers"],
    )
    assert paths.status_code == 200
    path_body = paths.json()
    assert path_body["source_found"] is True
    assert path_body["target_found"] is True
    assert len(path_body["paths"]) == 2
    assert {
        path["transactions"][0]["transaction_id"] for path in path_body["paths"]
    } == {str(context["transactions"][0].id), str(context["transactions"][1].id)}
    assert all(
        datetime.fromisoformat(path["transactions"][0]["occurred_at"]).utcoffset()
        == UTC.utcoffset(BASE_TIME)
        for path in path_body["paths"]
    )

    bounded = client.get(
        _dataset_path(dataset_id, "graph/paths"),
        params={
            "source_account_id": account_id,
            "target_account_id": target_id,
            "max_hops": 2,
            "max_paths": 1,
        },
        headers=context["owner_headers"],
    )
    assert bounded.status_code == 200
    assert len(bounded.json()["paths"]) == 1
    assert bounded.json()["truncated"] is True
    assert client.get(
        _dataset_path(dataset_id, "graph/paths"),
        params={
            "source_account_id": account_id,
            "target_account_id": target_id,
            "max_hops": 9,
        },
        headers=context["owner_headers"],
    ).status_code == 422


def test_dataset_account_risk_ml_findings_and_job_analytics(graph_analytics_api):
    context = graph_analytics_api
    client = context["client"]
    dataset_id = context["dataset"].id
    headers = context["owner_headers"]

    analytics = client.get(_dataset_path(dataset_id, "analytics"), headers=headers)
    assert analytics.status_code == 200
    body = analytics.json()
    assert body["account_count"] == 4
    assert body["transaction_count"] == 4
    assert body["transaction_volume_by_currency"] == [
        {"currency": "EUR", "transaction_count": 1, "total_amount": "7.250000"},
        {"currency": "USD", "transaction_count": 3, "total_amount": "33.123457"},
    ]
    assert body["latest_analysis"]["status"] == "COMPLETED"
    assert body["latest_analysis"]["progress_percent"] == 100

    account_id = context["accounts"][0].id
    account_analytics = client.get(
        _dataset_path(dataset_id, f"accounts/{account_id}/analytics"),
        headers=headers,
    )
    assert account_analytics.status_code == 200
    assert account_analytics.json()["risk"]["score"] == "0.750000"
    assert account_analytics.json()["finding_count"] == 1

    risk = client.get(
        _dataset_path(dataset_id, "analytics/risk-distribution"), headers=headers
    )
    assert risk.status_code == 200
    bands = {item["risk_level"]: item for item in risk.json()["accounts_by_risk_level"]}
    assert bands["high"]["account_count"] == 1
    assert risk.json()["unscored_account_count"] == 3

    models = client.get(
        _dataset_path(dataset_id, "analytics/ml/models"), headers=headers
    )
    assert models.status_code == 200
    assert models.json()["total"] == 1
    model = models.json()["items"][0]
    assert model["model_name"] == "isolation_forest"
    assert model["feature_names"] == ["in_degree", "out_degree"]

    anomalies = client.get(
        _dataset_path(dataset_id, "analytics/ml/anomalies"), headers=headers
    )
    assert anomalies.status_code == 200
    assert anomalies.json()["total"] == 1
    finding_id = anomalies.json()["items"][0]["id"]
    finding = client.get(
        _dataset_path(dataset_id, f"findings/{finding_id}"), headers=headers
    )
    assert finding.status_code == 200
    assert finding.json()["evidence"]["model_score"] == "0.875000"
    assert finding.json()["accounts"][0]["account_id"]
    assert finding.json()["transactions"][0]["transaction_id"]

    job = client.get(
        _dataset_path(dataset_id, f"analysis/{context['job'].id}"), headers=headers
    )
    assert job.status_code == 200
    assert job.json()["progress_percent"] == 100


def test_empty_dataset_and_cross_user_scope(graph_analytics_api):
    context = graph_analytics_api
    client = context["client"]
    empty_id = context["empty_dataset"].id
    headers = context["owner_headers"]

    graph = client.get(_dataset_path(empty_id, "graph/overview"), headers=headers)
    assert graph.status_code == 200
    assert graph.json()["node_count"] == 0
    assert graph.json()["edge_count"] == 0
    assert graph.json()["directed_density"] == 0
    assert graph.json()["currency_totals"] == []

    analytics = client.get(_dataset_path(empty_id, "analytics"), headers=headers)
    assert analytics.status_code == 200
    assert analytics.json()["account_count"] == 0
    assert analytics.json()["transaction_count"] == 0
    assert analytics.json()["transaction_volume_by_currency"] == []

    models = client.get(_dataset_path(empty_id, "analytics/ml/models"), headers=headers)
    assert models.status_code == 200
    assert models.json()["total"] == 0
    anomalies = client.get(
        _dataset_path(empty_id, "analytics/ml/anomalies"), headers=headers
    )
    assert anomalies.status_code == 200
    assert anomalies.json()["total"] == 0

    other_dataset_id = context["other_dataset"].id
    hidden = client.get(
        _dataset_path(other_dataset_id, "graph/overview"), headers=headers
    )
    assert hidden.status_code == 404
    other_account_id = context["other_account"].id
    hidden_account = client.get(
        _dataset_path(other_dataset_id, f"accounts/{other_account_id}/analytics"),
        headers=headers,
    )
    assert hidden_account.status_code == 404
    assert client.get(
        _dataset_path(context["dataset"].id, "analytics")
    ).status_code == 401


@pytest.mark.integration
def test_postgres_graph_and_analytics_api_round_trip(monkeypatch: pytest.MonkeyPatch):
    """Exercise API DTOs against the migrated PostgreSQL schema, then roll back."""

    engine = get_engine()
    connection = engine.connect()
    outer_transaction = connection.begin()
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(TEST_JWT_SECRET))
    owner = User(
        email=f"phase12-pg-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.INVESTIGATOR.value,
    )
    try:
        with Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ) as db:
            db.add(owner)
            db.flush()
            dataset = Dataset(
                owner_id=owner.id,
                name=f"Phase 12 PostgreSQL {uuid4().hex}",
                status="ready",
            )
            db.add(dataset)
            db.flush()
            sender = Account(
                dataset_id=dataset.id,
                external_id=f"pg-sender-{uuid4().hex}",
                account_type="business",
            )
            receiver = Account(
                dataset_id=dataset.id,
                external_id=f"pg-receiver-{uuid4().hex}",
                account_type="personal",
            )
            db.add_all([sender, receiver])
            db.flush()
            db.add(
                Transaction(
                    dataset_id=dataset.id,
                    sender_account_id=sender.id,
                    receiver_account_id=receiver.id,
                    amount=Decimal("12345678901234.123456"),
                    currency="USD",
                    occurred_at=BASE_TIME,
                )
            )
            db.commit()
            dataset_id = dataset.id

        def override_get_db() -> Generator[Session, None, None]:
            db = Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )
            try:
                yield db
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as client:
            headers = {
                "Authorization": f"Bearer {create_access_token(owner.id)}"
            }
            overview = client.get(
                _dataset_path(dataset_id, "graph/overview"), headers=headers
            )
            assert overview.status_code == 200
            assert overview.json()["node_count"] == 2
            assert overview.json()["edge_count"] == 1
            assert overview.json()["currency_totals"][0]["total_amount"] == (
                "12345678901234.123456"
            )

            edges = client.get(
                _dataset_path(dataset_id, "graph/edges"), headers=headers
            )
            assert edges.status_code == 200
            assert edges.json()["items"][0]["data"]["amount"] == (
                "12345678901234.123456"
            )

            analytics = client.get(
                _dataset_path(dataset_id, "analytics"), headers=headers
            )
            assert analytics.status_code == 200
            assert analytics.json()["account_count"] == 2
            assert analytics.json()["transaction_count"] == 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        outer_transaction.rollback()
        connection.close()
