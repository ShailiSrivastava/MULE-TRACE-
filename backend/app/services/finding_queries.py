"""Owner-scoped, bounded query workflows for persisted findings and risk."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    DetectionFinding,
    FindingAccount,
    FindingObservation,
    FindingStatusHistory,
    FindingTransaction,
    RiskAssessment,
    User,
)
from app.services.dataset_access import require_owned_dataset
from app.services.findings import FindingNotFound


def _latest_finding_risk(dataset_id: UUID):
    ranked = select(
        RiskAssessment.finding_id.label("finding_id"),
        RiskAssessment.score.label("score"),
        RiskAssessment.risk_level.label("risk_level"),
        RiskAssessment.scoring_model_version.label("scoring_model_version"),
        RiskAssessment.assessed_at.label("assessed_at"),
        RiskAssessment.analysis_job_id.label("analysis_job_id"),
        func.row_number()
        .over(
            partition_by=RiskAssessment.finding_id,
            order_by=(RiskAssessment.assessed_at.desc(), RiskAssessment.id.desc()),
        )
        .label("row_number"),
    ).where(
        RiskAssessment.dataset_id == dataset_id,
        RiskAssessment.finding_id.is_not(None),
    )
    return ranked.subquery()


def _account_count_expression():
    return (
        select(func.count(FindingAccount.account_id))
        .where(
            FindingAccount.dataset_id == DetectionFinding.dataset_id,
            FindingAccount.finding_id == DetectionFinding.id,
        )
        .correlate(DetectionFinding)
        .scalar_subquery()
    )


def _transaction_count_expression():
    return (
        select(func.count(FindingTransaction.transaction_id))
        .where(
            FindingTransaction.dataset_id == DetectionFinding.dataset_id,
            FindingTransaction.finding_id == DetectionFinding.id,
        )
        .correlate(DetectionFinding)
        .scalar_subquery()
    )


def _list_conditions(
    *,
    dataset_id: UUID,
    latest_risk,
    category: str | None,
    severity: str | None,
    risk_level: str | None,
    status: str | None,
    assigned_to_id: UUID | None,
    unassigned: bool,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list[Any]:
    conditions: list[Any] = [DetectionFinding.dataset_id == dataset_id]
    if category is not None:
        conditions.append(DetectionFinding.category == category)
    if severity is not None:
        conditions.append(DetectionFinding.severity == severity)
    if risk_level is not None:
        conditions.append(latest_risk.c.risk_level == risk_level)
    if status is not None:
        conditions.append(DetectionFinding.status == status)
    if assigned_to_id is not None:
        conditions.append(DetectionFinding.assigned_to_id == assigned_to_id)
    if unassigned:
        conditions.append(DetectionFinding.assigned_to_id.is_(None))
    if start_at is not None:
        conditions.append(DetectionFinding.last_detected_at >= start_at)
    if end_at is not None:
        conditions.append(DetectionFinding.last_detected_at <= end_at)
    return conditions


def list_findings(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    category: str | None = None,
    severity: str | None = None,
    risk_level: str | None = None,
    status: str | None = None,
    assigned_to_id: UUID | None = None,
    unassigned: bool = False,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sort_by: str = "last_detected_at",
    sort_order: str = "desc",
) -> tuple[list[tuple[Any, ...]], int]:
    """List findings with count/risk columns in a fixed number of queries."""

    require_owned_dataset(db, dataset_id, actor.id)
    latest = _latest_finding_risk(dataset_id)
    conditions = _list_conditions(
        dataset_id=dataset_id,
        latest_risk=latest,
        category=category,
        severity=severity,
        risk_level=risk_level,
        status=status,
        assigned_to_id=assigned_to_id,
        unassigned=unassigned,
        start_at=start_at,
        end_at=end_at,
    )
    count_statement = (
        select(func.count(DetectionFinding.id))
        .outerjoin(
            latest,
            and_(
                latest.c.finding_id == DetectionFinding.id,
                latest.c.row_number == 1,
            ),
        )
        .where(*conditions)
    )
    total = int(db.scalar(count_statement) or 0)

    sort_columns = {
        "created_at": DetectionFinding.created_at,
        "first_detected_at": DetectionFinding.first_detected_at,
        "last_detected_at": DetectionFinding.last_detected_at,
        "severity": case(
            (DetectionFinding.severity == "critical", 0),
            (DetectionFinding.severity == "high", 1),
            (DetectionFinding.severity == "medium", 2),
            (DetectionFinding.severity == "low", 3),
            else_=4,
        ),
        "status": DetectionFinding.status,
    }
    sort_column = sort_columns[sort_by]
    ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    rows = db.execute(
        select(
            DetectionFinding,
            _account_count_expression().label("account_count"),
            _transaction_count_expression().label("transaction_count"),
            latest.c.score.label("risk_score"),
            latest.c.risk_level.label("risk_level"),
            latest.c.scoring_model_version.label("scoring_model_version"),
        )
        .outerjoin(
            latest,
            and_(
                latest.c.finding_id == DetectionFinding.id,
                latest.c.row_number == 1,
            ),
        )
        .where(*conditions)
        .order_by(ordering, DetectionFinding.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [tuple(row) for row in rows], total


def get_finding_detail(
    db: Session,
    *,
    dataset_id: UUID,
    finding_id: UUID,
    actor: User,
) -> tuple[
    DetectionFinding,
    list[FindingAccount],
    list[FindingTransaction],
    list[FindingObservation],
    list[FindingStatusHistory],
    RiskAssessment | None,
]:
    require_owned_dataset(db, dataset_id, actor.id)
    finding = db.scalar(
        select(DetectionFinding).where(
            DetectionFinding.dataset_id == dataset_id,
            DetectionFinding.id == finding_id,
        )
    )
    if finding is None:
        raise FindingNotFound
    accounts = list(
        db.scalars(
            select(FindingAccount)
            .where(
                FindingAccount.dataset_id == dataset_id,
                FindingAccount.finding_id == finding_id,
            )
            .order_by(FindingAccount.account_id)
        ).all()
    )
    transactions = list(
        db.scalars(
            select(FindingTransaction)
            .where(
                FindingTransaction.dataset_id == dataset_id,
                FindingTransaction.finding_id == finding_id,
            )
            .order_by(FindingTransaction.transaction_id)
        ).all()
    )
    observations = list(
        db.scalars(
            select(FindingObservation)
            .where(
                FindingObservation.dataset_id == dataset_id,
                FindingObservation.finding_id == finding_id,
            )
            .order_by(FindingObservation.observed_at, FindingObservation.analysis_job_id)
        ).all()
    )
    status_history = list(
        db.scalars(
            select(FindingStatusHistory)
            .where(
                FindingStatusHistory.dataset_id == dataset_id,
                FindingStatusHistory.finding_id == finding_id,
            )
            .order_by(FindingStatusHistory.changed_at, FindingStatusHistory.id)
        ).all()
    )
    risk = db.scalar(
        select(RiskAssessment)
        .where(
            RiskAssessment.dataset_id == dataset_id,
            RiskAssessment.finding_id == finding_id,
        )
        .order_by(RiskAssessment.assessed_at.desc(), RiskAssessment.id.desc())
        .limit(1)
    )
    return finding, accounts, transactions, observations, status_history, risk


def get_risk_summary(db: Session, *, dataset_id: UUID, actor: User) -> dict[str, Any]:
    require_owned_dataset(db, dataset_id, actor.id)
    total = int(
        db.scalar(
            select(func.count(DetectionFinding.id)).where(
                DetectionFinding.dataset_id == dataset_id
            )
        )
        or 0
    )
    grouped_fields = {
        "findings_by_category": DetectionFinding.category,
        "findings_by_severity": DetectionFinding.severity,
        "findings_by_status": DetectionFinding.status,
    }
    grouped: dict[str, dict[str, int]] = {}
    for name, column in grouped_fields.items():
        grouped[name] = {
            **(
                {key: 0 for key in ("info", "low", "medium", "high", "critical")}
                if name == "findings_by_severity"
                else {key: 0 for key in ("NEW", "REVIEWING", "RESOLVED", "DISMISSED")}
                if name == "findings_by_status"
                else {}
            ),
            **{
            str(key): int(count)
            for key, count in db.execute(
                select(column, func.count(DetectionFinding.id))
                .where(DetectionFinding.dataset_id == dataset_id)
                .group_by(column)
                .order_by(column)
            )
            },
        }

    latest = _latest_finding_risk(dataset_id)
    risk_rows = db.execute(
        select(latest.c.risk_level, func.count(DetectionFinding.id))
        .select_from(DetectionFinding)
        .outerjoin(
            latest,
            and_(
                latest.c.finding_id == DetectionFinding.id,
                latest.c.row_number == 1,
            ),
        )
        .where(DetectionFinding.dataset_id == dataset_id)
        .group_by(latest.c.risk_level)
    )
    findings_by_risk: dict[str, int] = {
        "low": 0,
        "medium": 0,
        "high": 0,
        "critical": 0,
        "unscored": 0,
    }
    for level, count in risk_rows:
        findings_by_risk[str(level) if level is not None else "unscored"] = int(count)

    affected_accounts = int(
        db.scalar(
            select(func.count(func.distinct(FindingAccount.account_id))).where(
                FindingAccount.dataset_id == dataset_id
            )
        )
        or 0
    )
    affected_transactions = int(
        db.scalar(
            select(func.count(func.distinct(FindingTransaction.transaction_id))).where(
                FindingTransaction.dataset_id == dataset_id
            )
        )
        or 0
    )
    latest_analysis = db.scalar(
        select(func.max(FindingObservation.observed_at)).where(
            FindingObservation.dataset_id == dataset_id
        )
    )
    return {
        "dataset_id": dataset_id,
        "total_findings": total,
        **grouped,
        "findings_by_risk_level": findings_by_risk,
        "affected_account_count": affected_accounts,
        "affected_transaction_count": affected_transactions,
        "latest_analysis_at": latest_analysis,
    }


def get_account_risk(
    db: Session, *, dataset_id: UUID, account_id: UUID, actor: User
) -> tuple[RiskAssessment | None, int]:
    require_owned_dataset(db, dataset_id, actor.id)
    account_exists = db.scalar(
        select(Account.id).where(
            Account.dataset_id == dataset_id,
            Account.id == account_id,
        )
    )
    if account_exists is None:
        raise FindingNotFound
    assessment = db.scalar(
        select(RiskAssessment)
        .where(
            RiskAssessment.dataset_id == dataset_id,
            RiskAssessment.account_id == account_id,
            RiskAssessment.finding_id.is_(None),
        )
        .order_by(RiskAssessment.assessed_at.desc(), RiskAssessment.id.desc())
        .limit(1)
    )
    if assessment is None:
        return None, 0
    components = assessment.score_components.get("findings", [])
    return assessment, len(components) if isinstance(components, list) else 0
