"""Owner-scoped, aggregate-first dataset and ML analytics queries."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AnalysisJob,
    Dataset,
    DetectionFinding,
    FindingAccount,
    MLModelRegistryRecord,
    RiskAssessment,
    Transaction,
    User,
)
from app.services.dataset_access import DatasetScopeNotFound, require_owned_dataset
from app.services.finding_queries import get_risk_summary


def dataset_analytics(db: Session, *, dataset_id: UUID, actor: User) -> dict:
    """Return actual persisted dataset counts, volumes, risk, and job status."""

    require_owned_dataset(db, dataset_id, actor.id)
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id))
    if dataset is None:
        raise DatasetScopeNotFound

    account_count = int(
        db.scalar(select(func.count(Account.id)).where(Account.dataset_id == dataset_id))
        or 0
    )
    transaction_count = int(
        db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.dataset_id == dataset_id
            )
        )
        or 0
    )
    volumes = db.execute(
        select(
            Transaction.currency,
            func.count(Transaction.id),
            func.coalesce(func.sum(Transaction.amount), 0),
        )
        .where(Transaction.dataset_id == dataset_id)
        .group_by(Transaction.currency)
        .order_by(Transaction.currency)
    ).all()
    latest_analysis = db.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.dataset_id == dataset_id)
        .order_by(AnalysisJob.created_at.desc(), AnalysisJob.id.desc())
        .limit(1)
    )
    return {
        "dataset": dataset,
        "account_count": account_count,
        "transaction_count": transaction_count,
        "transaction_volume_by_currency": [
            {
                "currency": currency,
                "transaction_count": int(count),
                "total_amount": total_amount,
            }
            for currency, count, total_amount in volumes
        ],
        "finding_summary": get_risk_summary(
            db, dataset_id=dataset_id, actor=actor
        ),
        "latest_analysis": latest_analysis,
    }


def account_finding_counts(
    db: Session,
    *,
    dataset_id: UUID,
    account_id: UUID,
    actor: User,
) -> tuple[int, int]:
    """Count linked findings with one grouped query and no relationship loads."""

    require_owned_dataset(db, dataset_id, actor.id)
    counts = db.execute(
        select(
            func.count(func.distinct(FindingAccount.finding_id)),
            func.count(
                func.distinct(
                    case(
                        (
                            DetectionFinding.status.in_(("NEW", "REVIEWING")),
                            FindingAccount.finding_id,
                        ),
                        else_=None,
                    )
                )
            ),
        )
        .select_from(FindingAccount)
        .join(
            DetectionFinding,
            (DetectionFinding.dataset_id == FindingAccount.dataset_id)
            & (DetectionFinding.id == FindingAccount.finding_id),
        )
        .where(
            FindingAccount.dataset_id == dataset_id,
            FindingAccount.account_id == account_id,
        )
    ).one()
    return int(counts[0] or 0), int(counts[1] or 0)


def account_risk_distribution(
    db: Session, *, dataset_id: UUID, actor: User
) -> dict:
    """Aggregate the latest persisted account scores, never infer probabilities."""

    require_owned_dataset(db, dataset_id, actor.id)
    ranked = select(
        RiskAssessment.account_id.label("account_id"),
        RiskAssessment.score.label("score"),
        RiskAssessment.risk_level.label("risk_level"),
        RiskAssessment.assessed_at.label("assessed_at"),
        func.row_number()
        .over(
            partition_by=RiskAssessment.account_id,
            order_by=(RiskAssessment.assessed_at.desc(), RiskAssessment.id.desc()),
        )
        .label("row_number"),
    ).where(
        RiskAssessment.dataset_id == dataset_id,
        RiskAssessment.account_id.is_not(None),
        RiskAssessment.finding_id.is_(None),
    )
    latest = ranked.subquery()
    rows = db.execute(
        select(
            latest.c.risk_level,
            func.count(latest.c.account_id),
            func.avg(latest.c.score),
        )
        .where(latest.c.row_number == 1)
        .group_by(latest.c.risk_level)
    ).all()
    by_level = {
        str(level): {"account_count": int(count), "average_score": average}
        for level, count, average in rows
    }
    scored_count = int(
        db.scalar(
            select(func.count(latest.c.account_id)).where(latest.c.row_number == 1)
        )
        or 0
    )
    account_count = int(
        db.scalar(select(func.count(Account.id)).where(Account.dataset_id == dataset_id))
        or 0
    )
    latest_at = db.scalar(
        select(func.max(latest.c.assessed_at)).where(latest.c.row_number == 1)
    )
    risk_summary = get_risk_summary(db, dataset_id=dataset_id, actor=actor)
    return {
        "dataset_id": dataset_id,
        "accounts_by_risk_level": by_level,
        "unscored_account_count": max(account_count - scored_count, 0),
        "latest_account_assessment_at": latest_at,
        "findings_by_risk_level": risk_summary["findings_by_risk_level"],
    }


def list_dataset_ml_models(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    entity_type: Literal["ACCOUNT", "TRANSACTION"] | None = None,
    status: Literal["TRAINED", "EVALUATED", "ARCHIVED"] | None = None,
    model_name: str | None = None,
) -> tuple[list[MLModelRegistryRecord], int]:
    """List registry entries trained on this owned dataset only."""

    require_owned_dataset(db, dataset_id, actor.id)
    conditions = [MLModelRegistryRecord.training_dataset_id == dataset_id]
    if entity_type is not None:
        conditions.append(MLModelRegistryRecord.entity_type == entity_type)
    if status is not None:
        conditions.append(MLModelRegistryRecord.status == status)
    if model_name is not None:
        conditions.append(MLModelRegistryRecord.model_name == model_name)
    total = int(
        db.scalar(
            select(func.count(MLModelRegistryRecord.id)).where(*conditions)
        )
        or 0
    )
    rows = db.scalars(
        select(MLModelRegistryRecord)
        .where(*conditions)
        .order_by(
            MLModelRegistryRecord.created_at.desc(),
            MLModelRegistryRecord.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total
