"""HTTP coverage for owner-scoped finding, lifecycle, and risk APIs."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db
from app.core.model_base import Base
from app.detection.models import DetectionRunResult, create_finding
from app.main import app
from app.models import (
    Account,
    AnalysisJob,
    AuditLog,
    Dataset,
    FindingStatusHistory,
    RiskAssessment,
    Transaction,
    User,
    UserRole,
)
from app.risk import RiskScoringConfig
from app.security.tokens import create_access_token
from app.services.findings import persist_detection_run
from app.services.risk_scoring import (
    RiskAssessmentConflict,
    calculate_and_persist_risk_scores,
)

TEST_JWT_SECRET = "phase-nine-test-secret-value-at-least-32-bytes"
BASE_TIME = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest.fixture
def finding_api(monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
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
        email=f"investigator-{uuid4().hex}@example.com",
        password_hash="test-hash",
        role=UserRole.INVESTIGATOR.value,
    )
    analyst = User(
        email=f"analyst-{uuid4().hex}@example.com",
        password_hash="test-hash",
        role=UserRole.ANALYST.value,
    )
    other_owner = User(
        email=f"other-{uuid4().hex}@example.com", password_hash="test-hash"
    )
    assignee = User(
        email=f"assignee-{uuid4().hex}@example.com",
        password_hash="test-hash",
        role=UserRole.INVESTIGATOR.value,
    )
    inactive_assignee = User(
        email=f"inactive-{uuid4().hex}@example.com",
        password_hash="test-hash",
        role=UserRole.INVESTIGATOR.value,
        is_active=False,
    )

    with factory() as db:
        db.add_all([owner, analyst, other_owner, assignee, inactive_assignee])
        db.flush()
        dataset = Dataset(owner_id=owner.id, name=f"Findings {uuid4().hex}")
        analyst_dataset = Dataset(owner_id=analyst.id, name=f"Analyst {uuid4().hex}")
        other_dataset = Dataset(owner_id=other_owner.id, name=f"Other {uuid4().hex}")
        db.add_all([dataset, analyst_dataset, other_dataset])
        db.flush()
        accounts = [
            Account(dataset_id=dataset.id, external_id=f"acct-{uuid4().hex}")
            for _ in range(3)
        ]
        db.add_all(accounts)
        db.flush()
        transactions = [
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=accounts[index].id,
                receiver_account_id=accounts[index + 1].id,
                amount=Decimal("25.123456"),
                currency="USD",
                occurred_at=BASE_TIME + timedelta(seconds=index),
            )
            for index in range(2)
        ]
        job = AnalysisJob(dataset_id=dataset.id, job_type="detection")
        db.add_all([*transactions, job])
        db.commit()
        for entity in [
            owner,
            analyst,
            other_owner,
            assignee,
            inactive_assignee,
            dataset,
            analyst_dataset,
            other_dataset,
            *accounts,
            *transactions,
            job,
        ]:
            db.refresh(entity)

        findings = (
            create_finding(
                detector_name="rapid_transfers",
                detector_version="1.0",
                category="rapid_transfer_chain",
                severity="high",
                title="Rapid transfer sequence",
                explanation="Several transfers occurred in a short window.",
                dataset_id=dataset.id,
                account_ids=(accounts[0].id, accounts[1].id),
                transaction_ids=(transactions[0].id, transactions[1].id),
                start_at=transactions[0].occurred_at,
                end_at=transactions[-1].occurred_at,
                evidence={"window_seconds": 60},
                parameters={"minimum_count": 2},
                deduplication_context=("rapid-sequence",),
            ),
            create_finding(
                detector_name="circular_movement",
                detector_version="1.0",
                category="circular_movement",
                severity="critical",
                title="Circular movement candidate",
                explanation="Transfers form a closed path candidate.",
                dataset_id=dataset.id,
                account_ids=(accounts[0].id, accounts[2].id),
                transaction_ids=(transactions[0].id, transactions[1].id),
                start_at=transactions[0].occurred_at,
                end_at=transactions[-1].occurred_at,
                evidence={"cycle_length": 3},
                parameters={"maximum_hops": 4},
                deduplication_context=("circular-sequence",),
            ),
        )
        run = DetectionRunResult(
            dataset_id=dataset.id, findings=findings, executions=()
        )
        persisted = persist_detection_run(
            db,
            dataset_id=dataset.id,
            analysis_job_id=job.id,
            actor=owner,
            result=run,
            observed_at=BASE_TIME,
        )
        assessments, _ = calculate_and_persist_risk_scores(
            db,
            dataset_id=dataset.id,
            analysis_job_id=job.id,
            actor=owner,
            assessed_at=BASE_TIME + timedelta(minutes=1),
        )
        finding_ids = [finding.id for finding in persisted.findings]
        account_ids = [account.id for account in accounts]
        db.commit()

    with TestClient(app) as client:
        yield {
            "client": client,
            "factory": factory,
            "owner": owner,
            "analyst": analyst,
            "other_owner": other_owner,
            "assignee": assignee,
            "inactive_assignee": inactive_assignee,
            "dataset": dataset,
            "analyst_dataset": analyst_dataset,
            "other_dataset": other_dataset,
            "accounts": accounts,
            "account_ids": account_ids,
            "job": job,
            "finding_ids": finding_ids,
            "assessments": assessments,
            "owner_headers": {
                "Authorization": f"Bearer {create_access_token(owner.id)}"
            },
            "analyst_headers": {
                "Authorization": f"Bearer {create_access_token(analyst.id)}"
            },
            "other_headers": {
                "Authorization": f"Bearer {create_access_token(other_owner.id)}"
            },
        }
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _findings_path(dataset_id: UUID) -> str:
    return f"/api/v1/datasets/{dataset_id}/findings"


def test_findings_list_pagination_filters_sort_and_authentication(finding_api):
    context = finding_api
    client = context["client"]
    path = _findings_path(context["dataset"].id)

    assert client.get(path).status_code == 401
    page = client.get(path, params={"page": 1, "page_size": 1}, headers=context["owner_headers"])
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert body["total_pages"] == 2
    assert len(body["items"]) == 1

    severity = client.get(path, params={"severity": "critical"}, headers=context["owner_headers"])
    assert severity.status_code == 200
    assert severity.json()["total"] == 1
    assert severity.json()["items"][0]["severity"] == "critical"

    category = client.get(
        path,
        params={"category": "rapid_transfer_chain"},
        headers=context["owner_headers"],
    )
    assert category.status_code == 200
    assert category.json()["total"] == 1

    critical_risk = client.get(
        path,
        params={"risk_level": "critical"},
        headers=context["owner_headers"],
    )
    assert critical_risk.status_code == 200
    assert critical_risk.json()["total"] == 1

    observed_window = client.get(
        path,
        params={"start_at": BASE_TIME.isoformat(), "end_at": BASE_TIME.isoformat()},
        headers=context["owner_headers"],
    )
    assert observed_window.status_code == 200
    assert observed_window.json()["total"] == 2

    sorted_rows = client.get(
        path,
        params={"sort_by": "severity", "sort_order": "asc"},
        headers=context["owner_headers"],
    )
    assert [item["severity"] for item in sorted_rows.json()["items"]] == [
        "critical",
        "high",
    ]

    invalid_sort = client.get(path, params={"sort_by": "amount"}, headers=context["owner_headers"])
    assert invalid_sort.status_code == 422
    invalid_page = client.get(path, params={"page": 0}, headers=context["owner_headers"])
    assert invalid_page.status_code == 422


def test_finding_detail_evidence_and_owner_scope(finding_api):
    context = finding_api
    dataset_id = context["dataset"].id
    finding_id = context["finding_ids"][0]
    path = f"{_findings_path(dataset_id)}/{finding_id}"

    detail = context["client"].get(path, headers=context["owner_headers"])
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == str(finding_id)
    assert body["parameters"] in (
        {"minimum_count": 2},
        {"maximum_hops": 4},
    )
    assert body["evidence"] in (
        {"window_seconds": 60},
        {"cycle_length": 3},
    )
    assert len(body["accounts"]) == 2
    assert len(body["transactions"]) == 2
    assert len(body["observations"]) == 1
    assert body["risk_score"] is not None

    cross_user = context["client"].get(path, headers=context["other_headers"])
    assert cross_user.status_code == 404
    missing = context["client"].get(
        f"{_findings_path(dataset_id)}/{uuid4()}", headers=context["owner_headers"]
    )
    assert missing.status_code == 404
    invalid_id = context["client"].get(
        f"{_findings_path(dataset_id)}/not-a-uuid", headers=context["owner_headers"]
    )
    assert invalid_id.status_code == 422


def test_status_lifecycle_role_checks_and_audit_history(finding_api):
    context = finding_api
    path = f"{_findings_path(context['dataset'].id)}/{context['finding_ids'][0]}/status"
    client = context["client"]

    missing_reason = client.patch(
        path,
        json={"status": "RESOLVED"},
        headers=context["owner_headers"],
    )
    assert missing_reason.status_code == 422

    analyst_update = client.patch(
        path,
        json={"status": "REVIEWING"},
        headers=context["analyst_headers"],
    )
    assert analyst_update.status_code == 403

    with context["factory"]() as db:
        owner = db.get(User, context["owner"].id)
        owner.role = UserRole.ADMIN.value
        db.commit()
    admin_headers = {
        "Authorization": f"Bearer {create_access_token(context['owner'].id)}"
    }

    reviewing = client.patch(
        path,
        json={"status": "REVIEWING"},
        headers=admin_headers,
    )
    assert reviewing.status_code == 200
    assert reviewing.json()["status"] == "REVIEWING"
    assert len(reviewing.json()["status_history"]) == 2
    resolved_filter = client.get(
        _findings_path(context["dataset"].id),
        params={"status": "REVIEWING"},
        headers=admin_headers,
    )
    assert resolved_filter.status_code == 200
    assert resolved_filter.json()["total"] == 1

    resolved = client.patch(
        path,
        json={"status": "RESOLVED", "reason": "Evidence reviewed."},
        headers=admin_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"

    invalid_transition = client.patch(
        path,
        json={"status": "NEW"},
        headers=admin_headers,
    )
    assert invalid_transition.status_code == 409

    with context["factory"]() as db:
        history_count = db.scalar(
            select(func.count()).select_from(FindingStatusHistory).where(
                FindingStatusHistory.finding_id == context["finding_ids"][0]
            )
        )
        audit_count = db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.entity_id == context["finding_ids"][0],
                AuditLog.event_type == "finding.status.changed",
            )
        )
    assert history_count == 3
    assert audit_count == 2

    dismissed_path = (
        f"{_findings_path(context['dataset'].id)}/"
        f"{context['finding_ids'][1]}/status"
    )
    missing_dismiss_reason = client.patch(
        dismissed_path,
        json={"status": "DISMISSED"},
        headers=admin_headers,
    )
    assert missing_dismiss_reason.status_code == 422
    dismissed = client.patch(
        dismissed_path,
        json={"status": "DISMISSED", "reason": "Reviewed and dismissed."},
        headers=admin_headers,
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "DISMISSED"


def test_assignment_requires_active_investigator_and_is_audited(finding_api):
    context = finding_api
    path = f"{_findings_path(context['dataset'].id)}/{context['finding_ids'][0]}/assignment"
    client = context["client"]

    assigned = client.patch(
        path,
        json={"assigned_to_id": str(context["assignee"].id)},
        headers=context["owner_headers"],
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to_id"] == str(context["assignee"].id)
    assigned_filter = client.get(
        _findings_path(context["dataset"].id),
        params={"assigned_to_id": str(context["assignee"].id)},
        headers=context["owner_headers"],
    )
    unassigned_filter = client.get(
        _findings_path(context["dataset"].id),
        params={"unassigned": True},
        headers=context["owner_headers"],
    )
    assert assigned_filter.json()["total"] == 1
    assert unassigned_filter.json()["total"] == 1

    reassigned = client.patch(
        path,
        json={"assigned_to_id": str(context["owner"].id)},
        headers=context["owner_headers"],
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["assigned_to_id"] == str(context["owner"].id)
    unassigned = client.patch(
        path,
        json={"assigned_to_id": None},
        headers=context["owner_headers"],
    )
    assert unassigned.status_code == 200
    assert unassigned.json()["assigned_to_id"] is None

    inactive = client.patch(
        path,
        json={"assigned_to_id": str(context["inactive_assignee"].id)},
        headers=context["owner_headers"],
    )
    assert inactive.status_code == 422

    invalid_role = client.patch(
        path,
        json={"assigned_to_id": str(context["analyst"].id)},
        headers=context["owner_headers"],
    )
    assert invalid_role.status_code == 422

    with context["factory"]() as db:
        audit_count = db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.entity_id == context["finding_ids"][0],
                AuditLog.event_type == "finding.assigned",
            )
        )
    assert audit_count == 2
    with context["factory"]() as db:
        unassign_count = db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.entity_id == context["finding_ids"][0],
                AuditLog.event_type == "finding.unassigned",
            )
        )
    assert unassign_count == 1


def test_risk_summary_and_account_risk_are_owner_scoped(finding_api):
    context = finding_api
    dataset_id = context["dataset"].id
    client = context["client"]

    summary_response = client.get(
        f"/api/v1/datasets/{dataset_id}/risk-summary",
        headers=context["owner_headers"],
    )
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_findings"] == 2
    assert summary["findings_by_severity"] == {
        "info": 0,
        "low": 0,
        "medium": 0,
        "high": 1,
        "critical": 1,
    }
    assert summary["findings_by_status"] == {
        "NEW": 2,
        "REVIEWING": 0,
        "RESOLVED": 0,
        "DISMISSED": 0,
    }
    assert summary["findings_by_risk_level"]["unscored"] == 0
    assert summary["affected_account_count"] == 3
    assert summary["affected_transaction_count"] == 2
    assert summary["latest_analysis_at"] is not None

    account_id = context["account_ids"][0]
    account_response = client.get(
        f"/api/v1/datasets/{dataset_id}/accounts/{account_id}/risk",
        headers=context["owner_headers"],
    )
    assert account_response.status_code == 200
    account_risk = account_response.json()
    assert account_risk["distinct_finding_count"] == 2
    assert Decimal(account_risk["risk"]["score"]) > 0

    cross_user = client.get(
        f"/api/v1/datasets/{dataset_id}/risk-summary",
        headers=context["other_headers"],
    )
    assert cross_user.status_code == 404
    foreign_account = client.get(
        f"/api/v1/datasets/{dataset_id}/accounts/{context['account_ids'][2]}/risk",
        headers=context["other_headers"],
    )
    assert foreign_account.status_code == 404


def test_risk_assessment_persistence_is_versioned_idempotent_and_explainable(finding_api):
    context = finding_api
    original = context["assessments"]
    assert len(original) == 5
    assert sum(row.finding_id is not None for row in original) == 2
    assert sum(row.account_id is not None for row in original) == 3
    assert {row.scoring_model_version for row in original} == {"1.0"}
    assert all("formula" in row.rationale for row in original)
    assert all(row.score_components for row in original)
    account_assessments = [row for row in original if row.account_id is not None]
    assert all(
        all("detector_weight" in component for component in row.score_components["findings"])
        for row in account_assessments
    )

    with context["factory"]() as db:
        unchanged, _ = calculate_and_persist_risk_scores(
            db,
            dataset_id=context["dataset"].id,
            analysis_job_id=context["job"].id,
            actor=context["owner"],
            assessed_at=BASE_TIME + timedelta(days=1),
        )
        assert len(unchanged) == 5
        row_count = db.scalar(
            select(func.count())
            .select_from(RiskAssessment)
            .where(RiskAssessment.analysis_job_id == context["job"].id)
        )
        audit_count = db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.event_type == "risk.assessments.calculated",
                AuditLog.entity_id == context["job"].id,
            )
        )
        assert row_count == 5
        assert audit_count == 1

        with pytest.raises(RiskAssessmentConflict, match="cannot be reused"):
            calculate_and_persist_risk_scores(
                db,
                dataset_id=context["dataset"].id,
                analysis_job_id=context["job"].id,
                actor=context["owner"],
                config=RiskScoringConfig(
                    model_version="1.0",
                    detector_weights={
                        "rapid_transfers": "0.20",
                        "circular_movement": "0.30",
                    },
                ),
            )

        revised, _ = calculate_and_persist_risk_scores(
            db,
            dataset_id=context["dataset"].id,
            analysis_job_id=context["job"].id,
            actor=context["owner"],
            config=RiskScoringConfig(
                model_version="investigator-tuned-2026",
                detector_weights={
                    "rapid_transfers": "0.20",
                    "circular_movement": "0.30",
                },
            ),
            assessed_at=BASE_TIME + timedelta(days=2),
        )
        assert len(revised) == 5
        assert {row.scoring_model_version for row in revised} == {
            "investigator-tuned-2026"
        }
        final_count = db.scalar(
            select(func.count())
            .select_from(RiskAssessment)
            .where(RiskAssessment.analysis_job_id == context["job"].id)
        )
        final_audit_count = db.scalar(
            select(func.count()).select_from(AuditLog).where(
                AuditLog.event_type == "risk.assessments.calculated",
                AuditLog.entity_id == context["job"].id,
            )
        )
    assert final_count == 10
    assert final_audit_count == 2


def test_findings_api_rejects_invalid_status_and_assignment_payloads(finding_api):
    context = finding_api
    root = f"{_findings_path(context['dataset'].id)}/{context['finding_ids'][0]}"
    headers = context["owner_headers"]

    invalid_status = context["client"].patch(
        f"{root}/status", json={"status": "CLOSED"}, headers=headers
    )
    assert invalid_status.status_code == 422
    extra_field = context["client"].patch(
        f"{root}/status",
        json={"status": "REVIEWING", "assigned_to_id": str(context["assignee"].id)},
        headers=headers,
    )
    assert extra_field.status_code == 422
    invalid_assignee = context["client"].patch(
        f"{root}/assignment", json={"assigned_to_id": "not-a-uuid"}, headers=headers
    )
    assert invalid_assignee.status_code == 422

