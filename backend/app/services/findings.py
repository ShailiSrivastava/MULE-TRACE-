"""Persistence and lifecycle workflows for Phase 8 detection findings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.model_base import utc_now
from app.core.observability import request_id_context
from app.detection.models import DetectionFinding as DetectionFindingResult
from app.models import (
    Account,
    AnalysisJob,
    AuditLog,
    DetectionFinding,
    FindingAccount,
    FindingObservation,
    FindingStatus,
    FindingStatusHistory,
    FindingTransaction,
    Transaction,
    User,
    UserRole,
)
from app.services.dataset_access import DatasetScopeNotFound, require_owned_dataset


class AnalysisJobNotFound(LookupError):
    """The requested analysis job is absent or belongs to another dataset."""


class FindingReferenceError(ValueError):
    """A finding references records outside its dataset."""


class FindingPersistenceConflict(RuntimeError):
    """Finding persistence encountered a uniqueness or integrity conflict."""


class FindingPersistenceError(RuntimeError):
    """A safe wrapper for unexpected database errors in finding workflows."""


class FindingNotFound(LookupError):
    """A finding is absent or outside the requested owned dataset."""


class InvalidFindingTransition(ValueError):
    """The requested lifecycle transition is not allowed."""


class FindingPermissionDenied(PermissionError):
    """The actor role cannot perform the requested finding action."""


class InvalidAssignee(ValueError):
    """The requested assignment target is not an active investigator."""


@dataclass(frozen=True, slots=True)
class FindingPersistenceResult:
    findings: tuple[DetectionFinding, ...]
    created_count: int
    observed_count: int
    unchanged_count: int


def _record_finding_audit(
    db: Session,
    *,
    actor_id: UUID | None,
    event_type: str,
    finding: DetectionFinding,
    details: dict[str, Any] | None = None,
) -> None:
    safe_details = {"dataset_id": str(finding.dataset_id)}
    if details:
        safe_details.update(details)
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            event_type=event_type,
            entity_type="detection_finding",
            entity_id=finding.id,
            request_id=request_id_context.get(),
            details=safe_details,
        )
    )


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    """Convert Phase 8 evidence to JSON-native values without changing meaning."""

    from pydantic import TypeAdapter

    return TypeAdapter(dict[str, Any]).dump_python(value, mode="json")


def persist_detection_run(
    db: Session,
    *,
    dataset_id: UUID,
    analysis_job_id: UUID,
    actor: User,
    result,
    observed_at: datetime | None = None,
) -> FindingPersistenceResult:
    """Persist each finding once per analysis job and keep run snapshots.

    Findings missing from this result are left untouched. Their status, evidence,
    associations, and prior observations remain available; callers can compare
    a job's observation links to identify findings not emitted in a later run.
    Reprocessing the same job is idempotent and does not advance timestamps or
    create duplicate observations/audit events.
    """

    if result.dataset_id != dataset_id or any(
        finding.dataset_id != dataset_id for finding in result.findings
    ):
        raise FindingReferenceError("Detection result dataset does not match the target dataset.")
    timestamp = observed_at or utc_now()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("observed_at must include a timezone offset.")
    timestamp = timestamp.astimezone(utc_now().tzinfo)
    unique: dict[str, DetectionFindingResult] = {}
    for finding in result.findings:
        previous = unique.get(finding.deduplication_key)
        if previous is not None and previous != finding:
            raise FindingPersistenceConflict(
                "A deduplication key maps to inconsistent finding evidence."
            )
        unique[finding.deduplication_key] = finding
    input_findings = tuple(
        sorted(unique.values(), key=lambda item: item.deduplication_key)
    )

    account_ids = {account_id for item in input_findings for account_id in item.account_ids}
    transaction_ids = {
        transaction_id for item in input_findings for transaction_id in item.transaction_ids
    }
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

        existing_accounts = set(
            db.scalars(
                select(Account.id).where(
                    Account.dataset_id == dataset_id,
                    Account.id.in_(account_ids),
                )
            ).all()
        ) if account_ids else set()
        existing_transactions = set(
            db.scalars(
                select(Transaction.id).where(
                    Transaction.dataset_id == dataset_id,
                    Transaction.id.in_(transaction_ids),
                )
            ).all()
        ) if transaction_ids else set()
        if existing_accounts != account_ids or existing_transactions != transaction_ids:
            raise FindingReferenceError(
                "One or more finding references are missing from the target dataset."
            )

        keys = [item.deduplication_key for item in input_findings]
        existing_rows = (
            db.scalars(
                select(DetectionFinding)
                .where(
                    DetectionFinding.dataset_id == dataset_id,
                    DetectionFinding.deduplication_key.in_(keys),
                )
                .with_for_update()
            ).all()
            if keys
            else []
        )
        existing_by_key = {item.deduplication_key: item for item in existing_rows}
        existing_ids = {item.id for item in existing_rows}
        observed_keys = set(
            db.execute(
                select(FindingObservation.finding_id).where(
                    FindingObservation.dataset_id == dataset_id,
                    FindingObservation.finding_id.in_(existing_ids),
                    FindingObservation.analysis_job_id == analysis_job_id,
                )
            ).scalars()
        ) if existing_ids else set()
        associated_accounts: dict[UUID, set[UUID]] = {}
        associated_transactions: dict[UUID, set[UUID]] = {}
        if existing_ids:
            for finding_id, account_id in db.execute(
                select(FindingAccount.finding_id, FindingAccount.account_id).where(
                    FindingAccount.dataset_id == dataset_id,
                    FindingAccount.finding_id.in_(existing_ids),
                )
            ):
                associated_accounts.setdefault(finding_id, set()).add(account_id)
            for finding_id, transaction_id in db.execute(
                select(
                    FindingTransaction.finding_id,
                    FindingTransaction.transaction_id,
                ).where(
                    FindingTransaction.dataset_id == dataset_id,
                    FindingTransaction.finding_id.in_(existing_ids),
                )
            ):
                associated_transactions.setdefault(finding_id, set()).add(transaction_id)

        persisted: list[DetectionFinding] = []
        created_count = observed_count = unchanged_count = 0
        for item in input_findings:
            finding = existing_by_key.get(item.deduplication_key)
            is_new = finding is None
            if finding is None:
                finding = DetectionFinding(
                    id=item.finding_id,
                    dataset_id=dataset_id,
                    detector_name=item.detector_name,
                    detector_version=item.detector_version,
                    category=item.category,
                    severity=item.severity,
                    title=item.title,
                    explanation=item.explanation,
                    deduplication_key=item.deduplication_key,
                    first_detected_at=timestamp,
                    last_detected_at=timestamp,
                    event_window_start=(
                        item.time_window.start_at if item.time_window else None
                    ),
                    event_window_end=(
                        item.time_window.end_at if item.time_window else None
                    ),
                    parameters=_json_safe(item.parameters),
                    evidence=_json_safe(item.evidence),
                )
                db.add(finding)
                db.flush()
                db.add_all(
                    FindingAccount(
                        dataset_id=dataset_id,
                        finding_id=finding.id,
                        account_id=account_id,
                        relationship_role="participant",
                    )
                    for account_id in item.account_ids
                )
                db.add_all(
                    FindingTransaction(
                        dataset_id=dataset_id,
                        finding_id=finding.id,
                        transaction_id=transaction_id,
                    )
                    for transaction_id in item.transaction_ids
                )
                db.add(
                    FindingStatusHistory(
                        dataset_id=dataset_id,
                        finding_id=finding.id,
                        from_status=None,
                        to_status=FindingStatus.NEW.value,
                        reason="Finding created from detector output.",
                        changed_by_id=actor.id,
                    )
                )
                _record_finding_audit(
                    db,
                    actor_id=actor.id,
                    event_type="finding.created",
                    finding=finding,
                    details={
                        "detector_name": item.detector_name,
                        "category": item.category,
                        "severity": item.severity,
                    },
                )
                created_count += 1
            else:
                if finding.id != item.finding_id:
                    raise FindingPersistenceConflict(
                        "Persisted finding ID does not match its stable detector ID."
                    )
                if associated_accounts.get(finding.id, set()) != set(item.account_ids) or (
                    associated_transactions.get(finding.id, set())
                    != set(item.transaction_ids)
                ):
                    raise FindingPersistenceConflict(
                        "Persisted finding references do not match its stable key."
                    )
                if finding.id in observed_keys:
                    unchanged_count += 1
                    persisted.append(finding)
                    continue

                # Keep a per-run snapshot while the canonical record reflects the
                # latest observation. Status and assignment are never reset.
                finding.detector_name = item.detector_name
                finding.detector_version = item.detector_version
                finding.category = item.category
                finding.severity = item.severity
                finding.title = item.title
                finding.explanation = item.explanation
                finding.event_window_start = (
                    item.time_window.start_at if item.time_window else None
                )
                finding.event_window_end = (
                    item.time_window.end_at if item.time_window else None
                )
                finding.parameters = _json_safe(item.parameters)
                finding.evidence = _json_safe(item.evidence)
                finding.last_detected_at = max(finding.last_detected_at, timestamp)
                finding.updated_at = utc_now()
                observed_count += 1

            db.add(
                FindingObservation(
                    dataset_id=dataset_id,
                    finding_id=finding.id,
                    analysis_job_id=analysis_job_id,
                    observed_at=timestamp,
                    parameters=_json_safe(item.parameters),
                    evidence=_json_safe(item.evidence),
                )
            )
            if not is_new:
                _record_finding_audit(
                    db,
                    actor_id=actor.id,
                    event_type="finding.observed_again",
                    finding=finding,
                    details={"analysis_job_id": str(analysis_job_id)},
                )
            persisted.append(finding)

        db.commit()
        for finding in persisted:
            db.refresh(finding)
        return FindingPersistenceResult(
            findings=tuple(persisted),
            created_count=created_count,
            observed_count=observed_count,
            unchanged_count=unchanged_count,
        )
    except (DatasetScopeNotFound, AnalysisJobNotFound, FindingReferenceError,
            FindingPersistenceConflict):
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise FindingPersistenceConflict(
            "Finding persistence failed because of a data conflict."
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise FindingPersistenceError("Finding persistence could not be completed.") from exc
    except Exception:
        db.rollback()
        raise


VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    FindingStatus.NEW.value: frozenset(
        {FindingStatus.REVIEWING.value, FindingStatus.DISMISSED.value}
    ),
    FindingStatus.REVIEWING.value: frozenset(
        {FindingStatus.RESOLVED.value, FindingStatus.DISMISSED.value}
    ),
    FindingStatus.RESOLVED.value: frozenset({FindingStatus.REVIEWING.value}),
    FindingStatus.DISMISSED.value: frozenset(),
}


def _finding_for_owner(
    db: Session, *, dataset_id: UUID, finding_id: UUID, actor: User
) -> DetectionFinding:
    require_owned_dataset(db, dataset_id, actor.id)
    finding = db.scalar(
        select(DetectionFinding)
        .where(
            DetectionFinding.dataset_id == dataset_id,
            DetectionFinding.id == finding_id,
        )
        .with_for_update()
    )
    if finding is None:
        raise FindingNotFound
    return finding


def transition_finding_status(
    db: Session,
    *,
    dataset_id: UUID,
    finding_id: UUID,
    actor: User,
    new_status: FindingStatus,
    reason: str | None,
) -> DetectionFinding:
    """Apply a valid, audited state transition without deleting evidence."""

    if actor.role not in {UserRole.ADMIN.value, UserRole.INVESTIGATOR.value}:
        raise FindingPermissionDenied
    normalized_reason = reason.strip() if reason is not None else None
    if new_status in {FindingStatus.RESOLVED, FindingStatus.DISMISSED} and not normalized_reason:
        raise InvalidFindingTransition("A reason is required to resolve or dismiss a finding.")
    try:
        finding = _finding_for_owner(
            db, dataset_id=dataset_id, finding_id=finding_id, actor=actor
        )
        previous = finding.status
        if previous == new_status.value:
            return finding
        if new_status.value not in VALID_TRANSITIONS.get(previous, frozenset()):
            raise InvalidFindingTransition("The requested finding status transition is not allowed.")
        finding.status = new_status.value
        finding.updated_at = utc_now()
        db.add(
            FindingStatusHistory(
                dataset_id=dataset_id,
                finding_id=finding.id,
                from_status=previous,
                to_status=new_status.value,
                reason=normalized_reason,
                changed_by_id=actor.id,
            )
        )
        _record_finding_audit(
            db,
            actor_id=actor.id,
            event_type="finding.status.changed",
            finding=finding,
            details={"from_status": previous, "to_status": new_status.value},
        )
        db.commit()
        db.refresh(finding)
        return finding
    except (DatasetScopeNotFound, FindingNotFound, FindingPermissionDenied,
            InvalidFindingTransition):
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise FindingPersistenceConflict("Finding status could not be saved.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise FindingPersistenceError("Finding status could not be saved.") from exc


def assign_finding(
    db: Session,
    *,
    dataset_id: UUID,
    finding_id: UUID,
    actor: User,
    assignee_id: UUID | None,
) -> DetectionFinding:
    """Assign or unassign a finding; targets must be active investigators."""

    if actor.role not in {UserRole.ADMIN.value, UserRole.INVESTIGATOR.value}:
        raise FindingPermissionDenied
    try:
        finding = _finding_for_owner(
            db, dataset_id=dataset_id, finding_id=finding_id, actor=actor
        )
        if assignee_id is not None:
            assignee = db.scalar(
                select(User).where(
                    User.id == assignee_id,
                    User.is_active.is_(True),
                    User.role == UserRole.INVESTIGATOR.value,
                )
            )
            if assignee is None:
                raise InvalidAssignee("Assignee must be an active investigator.")
        previous = finding.assigned_to_id
        if previous == assignee_id:
            return finding
        finding.assigned_to_id = assignee_id
        finding.updated_at = utc_now()
        _record_finding_audit(
            db,
            actor_id=actor.id,
            event_type="finding.assigned" if assignee_id else "finding.unassigned",
            finding=finding,
            details={
                "previous_assignee_id": str(previous) if previous else None,
                "assignee_id": str(assignee_id) if assignee_id else None,
            },
        )
        db.commit()
        db.refresh(finding)
        return finding
    except (DatasetScopeNotFound, FindingNotFound, FindingPermissionDenied, InvalidAssignee):
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise FindingPersistenceConflict("Finding assignment could not be saved.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise FindingPersistenceError("Finding assignment could not be saved.") from exc


def list_status_history(
    db: Session, *, dataset_id: UUID, finding_id: UUID
) -> list[FindingStatusHistory]:
    return list(
        db.scalars(
            select(FindingStatusHistory)
            .where(
                FindingStatusHistory.dataset_id == dataset_id,
                FindingStatusHistory.finding_id == finding_id,
            )
            .order_by(FindingStatusHistory.changed_at, FindingStatusHistory.id)
        ).all()
    )
