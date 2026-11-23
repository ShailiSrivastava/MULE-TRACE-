"""Case lifecycle, evidence retention, audit, and report API coverage."""

from __future__ import annotations

import csv
import io
from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event, Thread
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.exc import SQLAlchemyError
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
    AuditLog,
    Dataset,
    InvestigationCase,
    Transaction,
    User,
    UserRole,
)
from app.security.tokens import create_access_token
from app.services.cases import create_case, get_case, update_case
from app.services.findings import persist_detection_run

TEST_JWT_SECRET = "phase-thirteen-test-secret-at-least-32-bytes-long"
NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)


@pytest.fixture
def case_api(monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
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
        email=f"case-owner-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.INVESTIGATOR.value,
        display_name="Dataset Owner",
    )
    assignee = User(
        email=f"case-assignee-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.INVESTIGATOR.value,
        display_name="Assigned Investigator",
    )
    other_user = User(
        email=f"case-other-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.INVESTIGATOR.value,
        display_name="Other Investigator",
    )
    analyst = User(
        email=f"case-analyst-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.ANALYST.value,
        display_name="Data Analyst",
    )
    inactive_investigator = User(
        email=f"case-inactive-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.INVESTIGATOR.value,
        is_active=False,
    )

    with factory() as db:
        db.add_all([owner, assignee, other_user, analyst, inactive_investigator])
        db.flush()
        dataset = Dataset(
            owner_id=owner.id,
            name=f"Case dataset {uuid4().hex}",
            status="ready",
        )
        other_dataset = Dataset(
            owner_id=other_user.id,
            name=f"Other case dataset {uuid4().hex}",
            status="ready",
        )
        analyst_dataset = Dataset(
            owner_id=analyst.id,
            name=f"Analyst dataset {uuid4().hex}",
            status="ready",
        )
        db.add_all([dataset, other_dataset, analyst_dataset])
        db.flush()
        account = Account(
            dataset_id=dataset.id,
            external_id=f"private-{uuid4().hex}",
            account_type="business",
            institution_code='=HYPERLINK("https://unsafe.example")',
            country_code="US",
        )
        receiver = Account(
            dataset_id=dataset.id,
            external_id=f"receiver-{uuid4().hex}",
            account_type="personal",
            institution_code="BANK-B",
            country_code="GB",
        )
        other_account = Account(
            dataset_id=other_dataset.id,
            external_id=f"other-{uuid4().hex}",
        )
        db.add_all([account, receiver, other_account])
        db.flush()
        transaction = Transaction(
            dataset_id=dataset.id,
            sender_account_id=account.id,
            receiver_account_id=receiver.id,
            amount=Decimal("125.123456"),
            currency="USD",
            occurred_at=NOW,
            transaction_type="transfer",
            channel="online",
            status="settled",
        )
        job = AnalysisJob(
            dataset_id=dataset.id,
            created_by_id=owner.id,
            job_type="full_analysis",
            parameters={},
        )
        db.add_all([transaction, job])
        db.flush()
        detection = create_finding(
            detector_name="case_test_detector",
            detector_version="1.0",
            category="rapid_transfer",
            severity="high",
            title="Rapid transfer evidence",
            explanation="Transactions form a suspicious movement pattern.",
            dataset_id=dataset.id,
            account_ids=(account.id, receiver.id),
            transaction_ids=(transaction.id,),
            start_at=NOW,
            end_at=NOW,
            evidence={"transaction_ids": [str(transaction.id)], "score": "0.875000"},
            parameters={"window_minutes": 5},
            deduplication_context=(uuid4().hex,),
        )
        persisted = persist_detection_run(
            db,
            dataset_id=dataset.id,
            analysis_job_id=job.id,
            actor=owner,
            result=DetectionRunResult(
                dataset_id=dataset.id,
                findings=(detection,),
                executions=(),
            ),
            observed_at=NOW,
        )
        finding_id = persisted.findings[0].id
        db.commit()
        for entity in [
            owner,
            assignee,
            other_user,
            analyst,
            inactive_investigator,
            dataset,
            other_dataset,
            analyst_dataset,
            account,
            receiver,
            other_account,
            transaction,
            job,
        ]:
            db.refresh(entity)

    def token_headers(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    with TestClient(app) as client:
        yield {
            "client": client,
            "owner": owner,
            "assignee": assignee,
            "other_user": other_user,
            "analyst": analyst,
            "inactive_investigator": inactive_investigator,
            "dataset": dataset,
            "other_dataset": other_dataset,
            "analyst_dataset": analyst_dataset,
            "account": account,
            "receiver": receiver,
            "other_account": other_account,
            "transaction": transaction,
            "finding_id": finding_id,
            "owner_headers": token_headers(owner),
            "assignee_headers": token_headers(assignee),
            "other_headers": token_headers(other_user),
            "analyst_headers": token_headers(analyst),
            "inactive_headers": token_headers(inactive_investigator),
            "session_factory": factory,
        }
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _cases_path(dataset_id, suffix: str = "") -> str:
    return f"/api/v1/datasets/{dataset_id}/cases{suffix}"


def test_case_crud_lifecycle_pagination_filters_and_archive(case_api):
    client = case_api["client"]
    dataset_id = case_api["dataset"].id
    headers = case_api["owner_headers"]

    assert client.get(_cases_path(dataset_id)).status_code == 401
    first = client.post(
        _cases_path(dataset_id),
        headers=headers,
        json={
            "title": "  Shell network review  ",
            "description": "Initial review",
            "category": "money_laundering",
            "priority": "high",
        },
    )
    assert first.status_code == 201, first.text
    case = first.json()
    assert case["title"] == "Shell network review"
    assert case["category"] == "money_laundering"
    assert case["status"] == "open"
    assert case["priority"] == "high"
    assert case["created_at"] == case["opened_at"]
    case_id = case["id"]

    second = client.post(
        _cases_path(dataset_id),
        headers=headers,
        json={"title": "Different case", "category": "fraud"},
    )
    assert second.status_code == 201
    listed = client.get(
        _cases_path(dataset_id),
        headers=headers,
        params={"page": 1, "page_size": 1, "category": "money_laundering"},
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["total_pages"] == 1
    assert listed.json()["items"][0]["id"] == case_id

    detail = client.get(_cases_path(dataset_id, f"/{case_id}"), headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == case_id

    update = client.patch(
        _cases_path(dataset_id, f"/{case_id}"),
        headers=headers,
        json={
            "title": "Shell network case",
            "status": "in_review",
            "priority": "urgent",
        },
    )
    assert update.status_code == 200
    assert update.json()["status"] == "in_review"
    assert update.json()["priority"] == "urgent"

    invalid_transition = client.patch(
        _cases_path(dataset_id, f"/{case_id}"),
        headers=headers,
        json={"status": "closed"},
    )
    assert invalid_transition.status_code == 200
    invalid_transition = client.patch(
        _cases_path(dataset_id, f"/{case_id}"),
        headers=headers,
        json={"status": "in_review"},
    )
    assert invalid_transition.status_code == 409
    assert (
        client.patch(
            _cases_path(dataset_id, f"/{case_id}"),
            headers=headers,
            json={"assigned_to_id": str(case_api["assignee"].id)},
        ).status_code
        == 422
    )

    archived = client.delete(_cases_path(dataset_id, f"/{case_id}"), headers=headers)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert archived.json()["status"] == "closed"
    assert (
        client.get(
            _cases_path(dataset_id),
            headers=headers,
            params={"category": "money_laundering"},
        ).json()["total"]
        == 0
    )
    retained = client.get(
        _cases_path(dataset_id),
        headers=headers,
        params={"category": "money_laundering", "include_archived": True},
    )
    assert retained.status_code == 200
    assert retained.json()["total"] == 1

    assert (
        client.post(
            _cases_path(dataset_id), headers=headers, json={"title": "   "}
        ).status_code
        == 422
    )
    assert (
        client.get(_cases_path(dataset_id, f"/{uuid4()}"), headers=headers).status_code
        == 404
    )


def test_assignment_history_and_case_scoped_access(case_api):
    client = case_api["client"]
    dataset_id = case_api["dataset"].id
    created = client.post(
        _cases_path(dataset_id),
        headers=case_api["owner_headers"],
        json={"title": "Assignment target"},
    )
    assert created.status_code == 201
    case_id = created.json()["id"]

    invalid_targets = [case_api["analyst"], case_api["inactive_investigator"]]
    for user in invalid_targets:
        response = client.patch(
            _cases_path(dataset_id, f"/{case_id}/assignment"),
            headers=case_api["owner_headers"],
            json={"assigned_to_id": str(user.id)},
        )
        assert response.status_code == 422

    assigned = client.patch(
        _cases_path(dataset_id, f"/{case_id}/assignment"),
        headers=case_api["owner_headers"],
        json={"assigned_to_id": str(case_api["assignee"].id)},
    )
    assert assigned.status_code == 200
    assert assigned.json()["assigned_to"]["id"] == str(case_api["assignee"].id)
    assert "email" not in assigned.text.lower()
    assert (
        client.get(
            _cases_path(dataset_id, f"/{case_id}"), headers=case_api["assignee_headers"]
        ).status_code
        == 200
    )
    assert (
        client.get(
            _cases_path(dataset_id, f"/{case_id}"), headers=case_api["other_headers"]
        ).status_code
        == 404
    )

    removed_by_previous_assignee = client.patch(
        _cases_path(dataset_id, f"/{case_id}/assignment"),
        headers=case_api["assignee_headers"],
        json={"assigned_to_id": None},
    )
    assert removed_by_previous_assignee.status_code == 200
    assert removed_by_previous_assignee.json()["assigned_to_id"] is None
    assert (
        client.get(
            _cases_path(dataset_id, f"/{case_id}"), headers=case_api["assignee_headers"]
        ).status_code
        == 404
    )

    reassigned = client.patch(
        _cases_path(dataset_id, f"/{case_id}/assignment"),
        headers=case_api["owner_headers"],
        json={"assigned_to_id": str(case_api["assignee"].id)},
    )
    assert reassigned.status_code == 200
    reassigned = client.patch(
        _cases_path(dataset_id, f"/{case_id}/assignment"),
        headers=case_api["owner_headers"],
        json={"assigned_to_id": str(case_api["owner"].id)},
    )
    assert reassigned.status_code == 200
    assert (
        client.get(
            _cases_path(dataset_id, f"/{case_id}"), headers=case_api["assignee_headers"]
        ).status_code
        == 404
    )

    history = client.get(
        _cases_path(dataset_id, f"/{case_id}/assignments"),
        headers=case_api["owner_headers"],
    )
    assert history.status_code == 200
    assert history.json()["history"]["total"] == 4
    assert [item["event_type"] for item in history.json()["history"]["items"]] == [
        "case.assignment_reassigned",
        "case.assignment_assigned",
        "case.assignment_removed",
        "case.assignment_assigned",
    ]


def test_case_account_association_snapshot_and_soft_unlink(case_api):
    client = case_api["client"]
    dataset_id = case_api["dataset"].id
    case = client.post(
        _cases_path(dataset_id),
        headers=case_api["owner_headers"],
        json={"title": "Account link"},
    ).json()
    case_id = case["id"]

    link_url = _cases_path(dataset_id, f"/{case_id}/accounts")
    added = client.post(
        link_url,
        headers=case_api["owner_headers"],
        json={"account_id": str(case_api["account"].id), "note": "Primary account"},
    )
    assert added.status_code == 201
    assert added.json()["evidence_snapshot"]["institution_code"].startswith(
        "=HYPERLINK"
    )
    assert "private-" not in added.text
    duplicate = client.post(
        link_url,
        headers=case_api["owner_headers"],
        json={"account_id": str(case_api["account"].id)},
    )
    assert duplicate.status_code == 409
    wrong_dataset = client.post(
        link_url,
        headers=case_api["owner_headers"],
        json={"account_id": str(case_api["other_account"].id)},
    )
    assert wrong_dataset.status_code == 404

    linked = client.get(link_url, headers=case_api["owner_headers"])
    assert linked.status_code == 200
    assert linked.json()["total"] == 1
    removed = client.delete(
        _cases_path(
            dataset_id,
            f"/{case_id}/accounts/{case_api['account'].id}",
        ),
        headers=case_api["owner_headers"],
    )
    assert removed.status_code == 204
    assert client.get(link_url, headers=case_api["owner_headers"]).json()["total"] == 0
    history = client.get(
        link_url,
        headers=case_api["owner_headers"],
        params={"include_removed": True},
    )
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["removed_at"] is not None
    assert history.json()["items"][0]["evidence_snapshot"]["account_id"] == str(
        case_api["account"].id
    )
    account_update = client.patch(
        f"/api/v1/datasets/{dataset_id}/accounts/{case_api['account'].id}",
        headers=case_api["owner_headers"],
        json={"institution_code": "BANK-UPDATED"},
    )
    assert account_update.status_code == 200
    relinked = client.post(
        link_url,
        headers=case_api["owner_headers"],
        json={"account_id": str(case_api["account"].id)},
    )
    assert relinked.status_code == 201
    assert relinked.json()["evidence_snapshot"]["institution_code"] == "BANK-UPDATED"
    assert (
        relinked.json()["evidence_snapshot"]["history"][0]["institution_code"]
        .startswith("=HYPERLINK")
    )


def test_case_finding_snapshot_duplicate_and_unlink(case_api):
    client = case_api["client"]
    dataset_id = case_api["dataset"].id
    case = client.post(
        _cases_path(dataset_id),
        headers=case_api["owner_headers"],
        json={"title": "Finding link"},
    ).json()
    case_id = case["id"]
    path = _cases_path(dataset_id, f"/{case_id}/findings")

    link = client.post(
        path,
        headers=case_api["owner_headers"],
        json={"finding_id": str(case_api["finding_id"])},
    )
    assert link.status_code == 201, link.text
    body = link.json()
    assert body["title"] == "Rapid transfer evidence"
    assert body["evidence_snapshot"]["evidence"]["score"] == "0.875000"
    assert body["evidence_snapshot"]["transactions"][0]["amount"] == "125.123456"
    assert (
        client.post(
            path,
            headers=case_api["owner_headers"],
            json={"finding_id": str(case_api["finding_id"])},
        ).status_code
        == 409
    )

    changed = client.patch(
        f"/api/v1/datasets/{dataset_id}/findings/{case_api['finding_id']}/status",
        headers=case_api["owner_headers"],
        json={"status": "REVIEWING", "reason": "Investigation started"},
    )
    assert changed.status_code == 200
    current = client.get(path, headers=case_api["owner_headers"]).json()["items"][0]
    assert current["status"] == "REVIEWING"
    assert current["evidence_snapshot"]["status"] == "NEW"

    wrong_dataset = client.post(
        path,
        headers=case_api["owner_headers"],
        json={"finding_id": str(uuid4())},
    )
    assert wrong_dataset.status_code == 404
    assert (
        client.delete(
            _cases_path(dataset_id, f"/{case_id}/findings/{case_api['finding_id']}"),
            headers=case_api["owner_headers"],
        ).status_code
        == 204
    )
    historical = client.get(
        path, headers=case_api["owner_headers"], params={"include_removed": True}
    )
    assert historical.status_code == 200
    assert historical.json()["total"] == 1
    assert historical.json()["items"][0]["removed_at"] is not None
    relinked = client.post(
        path,
        headers=case_api["owner_headers"],
        json={"finding_id": str(case_api["finding_id"])},
    )
    assert relinked.status_code == 201
    assert relinked.json()["evidence_snapshot"]["status"] == "REVIEWING"
    assert relinked.json()["evidence_snapshot"]["history"][0]["status"] == "NEW"


def test_case_notes_versions_permissions_and_timeline(case_api):
    client = case_api["client"]
    dataset_id = case_api["dataset"].id
    case = client.post(
        _cases_path(dataset_id),
        headers=case_api["owner_headers"],
        json={"title": "Note history"},
    ).json()
    case_id = case["id"]
    notes_path = _cases_path(dataset_id, f"/{case_id}/notes")
    created = client.post(
        notes_path,
        headers=case_api["owner_headers"],
        json={"content": "Initial investigator observation."},
    )
    assert created.status_code == 201, created.text
    note_id = created.json()["id"]
    assert created.json()["revision_count"] == 1

    edited = client.patch(
        _cases_path(dataset_id, f"/{case_id}/notes/{note_id}"),
        headers=case_api["owner_headers"],
        json={"content": "Revised investigator observation."},
    )
    assert edited.status_code == 200
    assert edited.json()["revision_count"] == 2
    history = client.get(
        _cases_path(dataset_id, f"/{case_id}/notes/{note_id}/history"),
        headers=case_api["owner_headers"],
    )
    assert history.status_code == 200
    assert [item["content"] for item in history.json()["items"]] == [
        "Initial investigator observation.",
        "Revised investigator observation.",
    ]

    with case_api["session_factory"]() as db:
        audits = db.scalars(
            select(AuditLog).where(
                AuditLog.entity_type == "investigation_case",
                AuditLog.entity_id == UUID(case_id),
            )
        ).all()
        assert any(event.event_type == "case.note_created" for event in audits)
        assert any(event.event_type == "case.note_updated" for event in audits)
        assert all("observation" not in str(event.details) for event in audits)

    timeline = client.get(
        _cases_path(dataset_id, f"/{case_id}/timeline"),
        headers=case_api["owner_headers"],
    )
    assert timeline.status_code == 200
    events = timeline.json()["items"]
    assert [event["event_type"] for event in events][:3] == [
        "case.created",
        "case.note_created",
        "case.note_updated",
    ]
    timestamps = [datetime.fromisoformat(event["created_at"]) for event in events]
    assert timestamps == sorted(timestamps)
    assert all("observation" not in str(event["metadata"]) for event in events)

    archived = client.delete(
        _cases_path(dataset_id, f"/{case_id}/notes/{note_id}"),
        headers=case_api["owner_headers"],
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    assert (
        client.get(notes_path, headers=case_api["owner_headers"]).json()["total"] == 0
    )
    assert (
        client.get(
            notes_path,
            headers=case_api["owner_headers"],
            params={"include_archived": True},
        ).json()["total"]
        == 1
    )


def test_case_roles_dataset_scope_and_assignee_grant_is_case_limited(case_api):
    client = case_api["client"]
    dataset_id = case_api["dataset"].id
    case = client.post(
        _cases_path(dataset_id),
        headers=case_api["owner_headers"],
        json={"title": "Permission check"},
    ).json()
    case_id = case["id"]
    assert (
        client.patch(
            _cases_path(dataset_id, f"/{case_id}"),
            headers=case_api["analyst_headers"],
            json={"title": "Unauthorized update"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            _cases_path(case_api["other_dataset"].id),
            headers=case_api["owner_headers"],
        ).status_code
        == 404
    )
    assert (
        client.get(
            _cases_path(dataset_id), headers=case_api["other_headers"]
        ).status_code
        == 404
    )

    analyst_case = client.post(
        _cases_path(case_api["analyst_dataset"].id),
        headers=case_api["analyst_headers"],
        json={"title": "Analyst-owned case"},
    )
    assert analyst_case.status_code == 201
    assert (
        client.patch(
            _cases_path(
                case_api["analyst_dataset"].id, f"/{analyst_case.json()['id']}"
            ),
            headers=case_api["analyst_headers"],
            json={"title": "Denied lifecycle change"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            _cases_path(dataset_id, f"/{case_id}/assignment"),
            headers=case_api["owner_headers"],
            json={"assigned_to_id": str(case_api["assignee"].id)},
        ).status_code
        == 200
    )
    assert (
        client.get(
            _cases_path(dataset_id, f"/{case_id}"), headers=case_api["assignee_headers"]
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/datasets/{dataset_id}/accounts",
            headers=case_api["assignee_headers"],
        ).status_code
        == 404
    )


def test_case_reports_pdf_and_formula_safe_csv(case_api):
    client = case_api["client"]
    dataset_id = case_api["dataset"].id
    case = client.post(
        _cases_path(dataset_id),
        headers=case_api["owner_headers"],
        json={"title": "Export case", "description": "Bounded report content."},
    ).json()
    case_id = case["id"]
    assert (
        client.post(
            _cases_path(dataset_id, f"/{case_id}/accounts"),
            headers=case_api["owner_headers"],
            json={"account_id": str(case_api["account"].id)},
        ).status_code
        == 201
    )
    assert (
        client.post(
            _cases_path(dataset_id, f"/{case_id}/findings"),
            headers=case_api["owner_headers"],
            json={"finding_id": str(case_api["finding_id"])},
        ).status_code
        == 201
    )
    assert (
        client.post(
            _cases_path(dataset_id, f"/{case_id}/notes"),
            headers=case_api["owner_headers"],
            json={"content": "Report note with <markup> and & symbols."},
        ).status_code
        == 201
    )

    pdf = client.get(
        _cases_path(dataset_id, f"/{case_id}/reports/investigation.pdf"),
        headers=case_api["owner_headers"],
    )
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.headers["content-disposition"].endswith(f'case-{case_id}.pdf"')
    assert pdf.content.startswith(b"%PDF-")

    csv_response = client.get(
        _cases_path(dataset_id, f"/{case_id}/exports/evidence.csv"),
        headers=case_api["owner_headers"],
    )
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert {row["record_type"] for row in rows} == {
        "account",
        "finding",
        "transaction",
    }
    account_row = next(row for row in rows if row["record_type"] == "account")
    assert account_row["institution_code"].startswith("'=HYPERLINK")
    transaction_row = next(row for row in rows if row["record_type"] == "transaction")
    assert transaction_row["amount"] == "125.123456"
    assert transaction_row["currency"] == "USD"
    assert "private-" not in csv_response.text
    assert (
        client.get(
            _cases_path(dataset_id, f"/{case_id}/exports/evidence.csv"),
            headers=case_api["owner_headers"],
            params={"limit": 1},
        ).status_code
        == 413
    )


@pytest.mark.integration
def test_postgres_case_api_round_trip_rolls_back(monkeypatch: pytest.MonkeyPatch):
    """Exercise migrated PostgreSQL case routes without leaving fixture rows."""

    engine = get_engine()
    connection = engine.connect()
    outer_transaction = connection.begin()
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(TEST_JWT_SECRET))
    owner = User(
        email=f"case-pg-{uuid4().hex}@example.com",
        password_hash="test-only-hash",
        role=UserRole.INVESTIGATOR.value,
        display_name="PostgreSQL Investigator",
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
                name=f"Case PostgreSQL {uuid4().hex}",
                status="ready",
            )
            db.add(dataset)
            db.flush()
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
            headers = {"Authorization": f"Bearer {create_access_token(owner.id)}"}
            created = client.post(
                _cases_path(dataset_id),
                headers=headers,
                json={
                    "title": "PostgreSQL case",
                    "category": "fraud",
                    "priority": "high",
                },
            )
            assert created.status_code == 201, created.text
            case_id = created.json()["id"]
            assert (
                created.json()["created_at"].endswith("Z")
                or "+00:00" in created.json()["created_at"]
            )

            note = client.post(
                _cases_path(dataset_id, f"/{case_id}/notes"),
                headers=headers,
                json={"content": "Persisted then rolled-back evidence note."},
            )
            assert note.status_code == 201, note.text
            pdf = client.get(
                _cases_path(dataset_id, f"/{case_id}/reports/investigation.pdf"),
                headers=headers,
            )
            assert pdf.status_code == 200
            assert pdf.content.startswith(b"%PDF-")
            csv_response = client.get(
                _cases_path(dataset_id, f"/{case_id}/exports/evidence.csv"),
                headers=headers,
            )
            assert csv_response.status_code == 200
            assert "record_type" in csv_response.text
    finally:
        app.dependency_overrides.pop(get_db, None)
        outer_transaction.rollback()
        connection.close()


@pytest.mark.integration
def test_postgres_case_updates_wait_for_row_lock_and_preserve_both_changes():
    """Concurrent case edits serialize through the case row lock."""
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required for row-lock integration testing.")

    owner_id: UUID | None = None
    dataset_id: UUID | None = None
    case_id: UUID | None = None
    with Session(engine, expire_on_commit=False) as setup:
        owner = User(
            email=f"case-lock-{uuid4().hex}@example.com",
            password_hash="test-only-hash",
            role=UserRole.INVESTIGATOR.value,
            display_name="Concurrency Test Investigator",
        )
        setup.add(owner)
        setup.flush()
        owner_id = owner.id
        dataset = Dataset(
            owner_id=owner_id,
            name=f"Case lock {uuid4().hex}",
            status="ready",
        )
        setup.add(dataset)
        setup.flush()
        dataset_id = dataset.id
        response = create_case(
            setup,
            dataset_id=dataset_id,
            actor=owner,
            fields={"title": "Concurrent edit review"},
        )
        case_id = response["id"]

    assert owner_id is not None and dataset_id is not None and case_id is not None
    first_writer = Session(engine, expire_on_commit=False)
    lock_query_started = Event()
    second_writer_finished = Event()
    outcome: dict[str, object] = {}

    def signal_for_update_lock(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        if "FOR UPDATE" in statement.upper():
            lock_query_started.set()

    def update_case_from_second_session() -> None:
        try:
            with Session(engine, expire_on_commit=False) as second_writer:
                actor = second_writer.get(User, owner_id)
                assert actor is not None
                outcome["response"] = update_case(
                    second_writer,
                    dataset_id=dataset_id,
                    case_id=case_id,
                    actor=actor,
                    fields={"title": "Concurrent title update"},
                )
        except (AssertionError, RuntimeError, SQLAlchemyError) as exc:
            outcome["error"] = exc
        finally:
            second_writer_finished.set()

    second_thread: Thread | None = None
    listener_registered = False
    try:
        first_actor = first_writer.get(User, owner_id)
        assert first_actor is not None
        locked_case = get_case(
            first_writer,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=first_actor,
            lock=True,
        )
        locked_case.description = "First transaction's description update."

        event.listen(engine, "before_cursor_execute", signal_for_update_lock)
        listener_registered = True
        second_thread = Thread(target=update_case_from_second_session, daemon=True)
        second_thread.start()
        assert lock_query_started.wait(timeout=5)
        assert not second_writer_finished.wait(timeout=0.1)

        first_writer.commit()
        assert second_writer_finished.wait(timeout=10)
        assert "error" not in outcome, repr(outcome.get("error"))
        response = outcome["response"]
        assert isinstance(response, dict)
        assert response["title"] == "Concurrent title update"
        assert response["description"] == "First transaction's description update."
    finally:
        if first_writer.in_transaction():
            first_writer.rollback()
        if second_thread is not None:
            second_thread.join(timeout=10)
        if listener_registered:
            event.remove(engine, "before_cursor_execute", signal_for_update_lock)
        first_writer.close()
        with Session(engine) as cleanup:
            cleanup.execute(
                delete(AuditLog).where(
                    AuditLog.entity_type == "investigation_case",
                    AuditLog.entity_id == case_id,
                )
            )
            cleanup.execute(
                delete(InvestigationCase).where(InvestigationCase.id == case_id)
            )
            cleanup.execute(delete(Dataset).where(Dataset.id == dataset_id))
            cleanup.execute(delete(User).where(User.id == owner_id))
            cleanup.commit()
