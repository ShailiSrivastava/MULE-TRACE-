"""Dataset-scoped persistence for deterministic risk score assessments."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.model_base import utc_now
from app.core.observability import request_id_context
from app.models import (
    AnalysisJob,
    AuditLog,
    DetectionFinding,
    FindingAccount,
    FindingObservation,
    RiskAssessment,
    User,
)
from app.risk import (
    FindingSignal,
    RiskScoringConfig,
    RiskScoringResult,
    calculate_risk_scores,
)
from app.services.dataset_access import DatasetScopeNotFound, require_owned_dataset
from app.services.findings import AnalysisJobNotFound, FindingPersistenceError


class RiskAssessmentConflict(RuntimeError):
    """A scoring assessment conflicts with a persisted scope/version key."""


def _finding_signals(
    db: Session, *, dataset_id: UUID, analysis_job_id: UUID
) -> list[FindingSignal]:
    findings = db.scalars(
        select(DetectionFinding)
        .join(
            FindingObservation,
            (FindingObservation.dataset_id == DetectionFinding.dataset_id)
            & (FindingObservation.finding_id == DetectionFinding.id),
        )
        .where(
            DetectionFinding.dataset_id == dataset_id,
            FindingObservation.analysis_job_id == analysis_job_id,
        )
        .order_by(DetectionFinding.deduplication_key)
    ).all()
    finding_ids = {finding.id for finding in findings}
    accounts_by_finding: dict[UUID, set[UUID]] = {}
    if finding_ids:
        for finding_id, account_id in db.execute(
            select(FindingAccount.finding_id, FindingAccount.account_id).where(
                FindingAccount.dataset_id == dataset_id,
                FindingAccount.finding_id.in_(finding_ids),
            )
        ):
            accounts_by_finding.setdefault(finding_id, set()).add(account_id)
    return [
        FindingSignal(
            finding_id=finding.id,
            deduplication_key=finding.deduplication_key,
            detector_name=finding.detector_name,
            category=finding.category,
            severity=finding.severity,
            account_ids=tuple(sorted(accounts_by_finding.get(finding.id, set()), key=str)),
        )
        for finding in findings
    ]


def calculate_and_persist_risk_scores(
    db: Session,
    *,
    dataset_id: UUID,
    analysis_job_id: UUID,
    actor: User,
    config: RiskScoringConfig | None = None,
    assessed_at: datetime | None = None,
) -> tuple[list[RiskAssessment], RiskScoringResult]:
    """Persist one score per finding and one aggregated score per affected account.

    A unique `(analysis job, subject, scoring version)` key makes repeated calls
    idempotent while retaining assessments from earlier configuration versions.
    """

    settings = config or RiskScoringConfig()
    timestamp = assessed_at or utc_now()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("assessed_at must include a timezone offset.")
    timestamp = timestamp.astimezone(utc_now().tzinfo)

    try:
        require_owned_dataset(db, dataset_id, actor.id)
        job_exists = db.scalar(
            select(AnalysisJob.id).where(
                AnalysisJob.id == analysis_job_id,
                AnalysisJob.dataset_id == dataset_id,
            )
        )
        if job_exists is None:
            raise AnalysisJobNotFound

        scoring_result = calculate_risk_scores(
            _finding_signals(db, dataset_id=dataset_id, analysis_job_id=analysis_job_id),
            settings,
        )
        existing_rows = db.scalars(
            select(RiskAssessment)
            .where(
                RiskAssessment.dataset_id == dataset_id,
                RiskAssessment.analysis_job_id == analysis_job_id,
                RiskAssessment.scoring_model_version == settings.model_version,
            )
            .with_for_update()
        ).all()
        existing_by_scope = {
            (row.finding_id, row.account_id): row for row in existing_rows
        }
        created = False
        saved: list[RiskAssessment] = []

        for finding_score in scoring_result.finding_scores:
            scope = (finding_score.finding_id, None)
            assessment = existing_by_scope.get(scope)
            if assessment is None:
                assessment = RiskAssessment(
                    dataset_id=dataset_id,
                    analysis_job_id=analysis_job_id,
                    finding_id=finding_score.finding_id,
                    account_id=None,
                    score=finding_score.score,
                    risk_level=finding_score.risk_level,
                    scoring_model_version=settings.model_version,
                    score_components=finding_score.components,
                    rationale={"formula": "detector_weight * category_weight * severity_contribution"},
                    assessed_at=timestamp,
                )
                db.add(assessment)
                created = True
            elif (
                assessment.score != finding_score.score
                or assessment.risk_level != finding_score.risk_level
                or assessment.score_components != finding_score.components
            ):
                raise RiskAssessmentConflict(
                    "A scoring model version cannot be reused with different inputs."
                )
            saved.append(assessment)

        for account_score in scoring_result.account_scores:
            scope = (None, account_score.account_id)
            assessment = existing_by_scope.get(scope)
            if assessment is None:
                assessment = RiskAssessment(
                    dataset_id=dataset_id,
                    analysis_job_id=analysis_job_id,
                    finding_id=None,
                    account_id=account_score.account_id,
                    score=account_score.score,
                    risk_level=account_score.risk_level,
                    scoring_model_version=settings.model_version,
                    score_components={"findings": list(account_score.components)},
                    rationale={"formula": "1 - product(1 - distinct_finding_signal)"},
                    assessed_at=timestamp,
                )
                db.add(assessment)
                created = True
            elif (
                assessment.score != account_score.score
                or assessment.risk_level != account_score.risk_level
                or assessment.score_components
                != {"findings": list(account_score.components)}
            ):
                raise RiskAssessmentConflict(
                    "A scoring model version cannot be reused with different inputs."
                )
            saved.append(assessment)

        if created:
            db.add(
                AuditLog(
                    actor_user_id=actor.id,
                    event_type="risk.assessments.calculated",
                    entity_type="analysis_job",
                    entity_id=analysis_job_id,
                    request_id=request_id_context.get(),
                    details={
                        "dataset_id": str(dataset_id),
                        "scoring_model_version": settings.model_version,
                        "finding_assessment_count": len(scoring_result.finding_scores),
                        "account_assessment_count": len(scoring_result.account_scores),
                    },
                )
            )
        db.commit()
        for assessment in saved:
            db.refresh(assessment)
        return saved, scoring_result
    except (DatasetScopeNotFound, AnalysisJobNotFound):
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise RiskAssessmentConflict("Risk assessments could not be saved.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise FindingPersistenceError("Risk assessment calculation could not be completed.") from exc
    except Exception:
        db.rollback()
        raise
