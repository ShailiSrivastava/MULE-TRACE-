"""Dataset-scoped case workflows with case-level assignment access grants."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.model_base import utc_now
from app.core.observability import request_id_context
from app.models import (
    Account,
    AuditLog,
    CaseAccount,
    CaseAlert,
    CaseFinding,
    CaseNote,
    CaseNoteRevision,
    Dataset,
    DetectionAlert,
    DetectionFinding,
    FindingAccount,
    FindingTransaction,
    InvestigationCase,
    Transaction,
    User,
    UserRole,
)
from app.services.dataset_access import DatasetScopeNotFound, require_owned_dataset

CASE_WRITER_ROLES = frozenset({UserRole.INVESTIGATOR.value, UserRole.ADMIN.value})
CASE_ASSIGNEE_ROLES = frozenset({UserRole.INVESTIGATOR.value, UserRole.ADMIN.value})
CASE_STATUS_TRANSITIONS = {
    "open": frozenset({"in_review", "resolved", "closed"}),
    "in_review": frozenset({"open", "resolved", "closed"}),
    "resolved": frozenset({"open", "in_review", "closed"}),
    "closed": frozenset({"open"}),
}
ASSIGNMENT_EVENTS = (
    "case.assignment_assigned",
    "case.assignment_reassigned",
    "case.assignment_removed",
)
MAX_EVIDENCE_SNAPSHOT_TRANSACTIONS = 500


class CaseNotFound(LookupError):
    """A case is missing or unavailable to the current user."""


class CaseResourceNotFound(LookupError):
    """An account, finding, or note is missing from an accessible case dataset."""


class CasePermissionDenied(PermissionError):
    """The user's role or relationship to a case does not permit the action."""


class InvalidCaseAssignee(ValueError):
    """The requested assignment target is inactive or has an unsuitable role."""


class InvalidCaseTransition(ValueError):
    """The case status transition is not part of the lifecycle contract."""


class CaseConflict(RuntimeError):
    """The case operation conflicts with persisted state or a unique constraint."""


class CaseExportLimitExceeded(ValueError):
    """The case report contains more evidence than the bounded export permits."""


def _audit_case(
    db: Session,
    *,
    case_record: InvestigationCase,
    actor_id: UUID | None,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    event = AuditLog(
        actor_user_id=actor_id,
        event_type=event_type,
        entity_type="investigation_case",
        entity_id=case_record.id,
        request_id=request_id_context.get(),
        details={"dataset_id": str(case_record.dataset_id), **(details or {})},
    )
    db.add(event)
    return event


def _case_access_predicate(actor_id: UUID):
    return or_(
        Dataset.owner_id == actor_id, InvestigationCase.assigned_to_id == actor_id
    )


def require_case_dataset_access(db: Session, *, dataset_id: UUID, actor: User) -> None:
    """Permit dataset owners and users with an explicit case assignment only."""

    assigned_case = select(InvestigationCase.id).where(
        InvestigationCase.dataset_id == Dataset.id,
        InvestigationCase.assigned_to_id == actor.id,
    )
    accessible = db.scalar(
        select(Dataset.id).where(
            Dataset.id == dataset_id,
            or_(Dataset.owner_id == actor.id, assigned_case.exists()),
        )
    )
    if accessible is None:
        raise DatasetScopeNotFound


def _owned_or_assigned_case_query(actor: User, *, dataset_id: UUID, case_id: UUID):
    return (
        select(InvestigationCase)
        .join(Dataset, Dataset.id == InvestigationCase.dataset_id)
        .where(
            InvestigationCase.dataset_id == dataset_id,
            InvestigationCase.id == case_id,
            _case_access_predicate(actor.id),
        )
    )


def get_case(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    lock: bool = False,
) -> InvestigationCase:
    statement = _owned_or_assigned_case_query(
        actor, dataset_id=dataset_id, case_id=case_id
    )
    if lock:
        statement = statement.with_for_update()
    record = db.scalar(statement)
    if record is None:
        raise CaseNotFound
    return record


def _case_view_query():
    creator = aliased(User)
    assignee = aliased(User)
    account_count = (
        select(func.count(CaseAccount.account_id))
        .where(
            CaseAccount.dataset_id == InvestigationCase.dataset_id,
            CaseAccount.case_id == InvestigationCase.id,
            CaseAccount.removed_at.is_(None),
        )
        .correlate(InvestigationCase)
        .scalar_subquery()
    )
    finding_count = (
        select(func.count(CaseFinding.finding_id))
        .where(
            CaseFinding.dataset_id == InvestigationCase.dataset_id,
            CaseFinding.case_id == InvestigationCase.id,
            CaseFinding.removed_at.is_(None),
        )
        .correlate(InvestigationCase)
        .scalar_subquery()
    )
    note_count = (
        select(func.count(CaseNote.id))
        .where(
            CaseNote.dataset_id == InvestigationCase.dataset_id,
            CaseNote.case_id == InvestigationCase.id,
            CaseNote.archived_at.is_(None),
        )
        .correlate(InvestigationCase)
        .scalar_subquery()
    )
    return (
        select(
            InvestigationCase,
            creator,
            assignee,
            account_count.label("account_count"),
            finding_count.label("finding_count"),
            note_count.label("note_count"),
        )
        .outerjoin(creator, creator.id == InvestigationCase.created_by_id)
        .outerjoin(assignee, assignee.id == InvestigationCase.assigned_to_id)
    )


def _user_summary(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.id,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
    }


def _case_response(row) -> dict[str, Any]:
    record, creator, assignee, account_count, finding_count, note_count = row
    return {
        "id": record.id,
        "dataset_id": record.dataset_id,
        "title": record.title,
        "description": record.description,
        "category": record.category,
        "priority": record.priority,
        "status": record.status,
        "created_by_id": record.created_by_id,
        "created_by": _user_summary(creator),
        "assigned_to_id": record.assigned_to_id,
        "assigned_to": _user_summary(assignee),
        "opened_at": record.opened_at,
        "closed_at": record.closed_at,
        "created_at": record.opened_at,
        "updated_at": record.updated_at,
        "archived_at": record.archived_at,
        "account_count": int(account_count or 0),
        "finding_count": int(finding_count or 0),
        "note_count": int(note_count or 0),
    }


def get_case_response(
    db: Session, *, dataset_id: UUID, case_id: UUID, actor: User
) -> dict[str, Any]:
    statement = (
        _case_view_query()
        .join(Dataset, Dataset.id == InvestigationCase.dataset_id)
        .where(
            InvestigationCase.dataset_id == dataset_id,
            InvestigationCase.id == case_id,
            _case_access_predicate(actor.id),
        )
    )
    row = db.execute(statement).one_or_none()
    if row is None:
        raise CaseNotFound
    return _case_response(row)


def _get_case_response_after_access_change(
    db: Session, *, dataset_id: UUID, case_id: UUID
) -> dict[str, Any]:
    """Build a final mutation response after the actor may have lost assignment access."""

    row = db.execute(
        _case_view_query()
        .join(Dataset, Dataset.id == InvestigationCase.dataset_id)
        .where(
            InvestigationCase.dataset_id == dataset_id,
            InvestigationCase.id == case_id,
        )
    ).one_or_none()
    if row is None:
        raise CaseNotFound
    return _case_response(row)


def create_case(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    fields: dict[str, Any],
) -> dict[str, Any]:
    require_owned_dataset(db, dataset_id, actor.id)
    record = InvestigationCase(
        dataset_id=dataset_id,
        created_by_id=actor.id,
        title=fields["title"],
        description=fields.get("description"),
        category=fields.get("category", "general"),
        priority=fields.get("priority", "medium"),
        status="open",
    )
    db.add(record)
    try:
        db.flush()
        _audit_case(
            db,
            case_record=record,
            actor_id=actor.id,
            event_type="case.created",
            details={"fields": ["title", "description", "category", "priority"]},
        )
        db.commit()
        db.refresh(record)
    except IntegrityError as exc:
        db.rollback()
        raise CaseConflict from exc
    return get_case_response(db, dataset_id=dataset_id, case_id=record.id, actor=actor)


def list_cases(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    assigned_to_id: UUID | None = None,
    unassigned: bool = False,
    include_archived: bool = False,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    require_case_dataset_access(db, dataset_id=dataset_id, actor=actor)
    conditions: list[Any] = [InvestigationCase.dataset_id == dataset_id]
    if not include_archived:
        conditions.append(InvestigationCase.archived_at.is_(None))
    if status is not None:
        conditions.append(InvestigationCase.status == status)
    if priority is not None:
        conditions.append(InvestigationCase.priority == priority)
    if category is not None:
        conditions.append(InvestigationCase.category == category)
    if assigned_to_id is not None:
        conditions.append(InvestigationCase.assigned_to_id == assigned_to_id)
    if unassigned:
        conditions.append(InvestigationCase.assigned_to_id.is_(None))
    scoped = (
        _case_view_query()
        .join(Dataset, Dataset.id == InvestigationCase.dataset_id)
        .where(*conditions, _case_access_predicate(actor.id))
    )
    total = int(
        db.scalar(
            select(func.count(InvestigationCase.id))
            .join(Dataset, Dataset.id == InvestigationCase.dataset_id)
            .where(*conditions, _case_access_predicate(actor.id))
        )
        or 0
    )
    columns = {
        "created_at": InvestigationCase.opened_at,
        "updated_at": InvestigationCase.updated_at,
        "opened_at": InvestigationCase.opened_at,
        "status": InvestigationCase.status,
        "priority": case(
            (InvestigationCase.priority == "urgent", 0),
            (InvestigationCase.priority == "high", 1),
            (InvestigationCase.priority == "medium", 2),
            else_=3,
        ),
        "title": InvestigationCase.title,
    }
    order = columns[sort_by]
    order = order.asc() if sort_order == "asc" else order.desc()
    rows = db.execute(
        scoped.order_by(order, InvestigationCase.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [_case_response(row) for row in rows], total


def update_case(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    fields: dict[str, Any],
) -> dict[str, Any]:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    if record.archived_at is not None:
        raise CaseConflict("Archived cases cannot be edited.")
    if "status" in fields:
        next_status = fields.pop("status")
        if next_status != record.status:
            if next_status not in CASE_STATUS_TRANSITIONS[record.status]:
                raise InvalidCaseTransition
            previous_status = record.status
            record.status = next_status
            if next_status == "closed":
                record.closed_at = utc_now()
            elif previous_status == "closed":
                record.closed_at = None
            _audit_case(
                db,
                case_record=record,
                actor_id=actor.id,
                event_type="case.status_changed",
                details={"from_status": previous_status, "to_status": next_status},
            )
    for name, value in fields.items():
        setattr(record, name, value)
    if fields:
        _audit_case(
            db,
            case_record=record,
            actor_id=actor.id,
            event_type="case.updated",
            details={"fields": sorted(fields)},
        )
    record.updated_at = utc_now()
    try:
        db.commit()
        db.refresh(record)
    except IntegrityError as exc:
        db.rollback()
        raise CaseConflict from exc
    return get_case_response(db, dataset_id=dataset_id, case_id=case_id, actor=actor)


def archive_case(
    db: Session, *, dataset_id: UUID, case_id: UUID, actor: User
) -> dict[str, Any]:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    if record.archived_at is not None:
        return get_case_response(
            db, dataset_id=dataset_id, case_id=case_id, actor=actor
        )
    now = utc_now()
    record.archived_at = now
    record.archived_by_id = actor.id
    if record.status != "closed":
        previous_status = record.status
        record.status = "closed"
        record.closed_at = now
        _audit_case(
            db,
            case_record=record,
            actor_id=actor.id,
            event_type="case.status_changed",
            details={
                "from_status": previous_status,
                "to_status": "closed",
                "reason": "archived",
            },
        )
    record.updated_at = now
    _audit_case(
        db,
        case_record=record,
        actor_id=actor.id,
        event_type="case.archived",
        details={"archived": True},
    )
    db.commit()
    db.refresh(record)
    return get_case_response(db, dataset_id=dataset_id, case_id=case_id, actor=actor)


def set_case_assignee(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    assignee_id: UUID | None,
) -> dict[str, Any]:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    if record.archived_at is not None:
        raise CaseConflict("Archived cases cannot be assigned.")
    assignee = None
    if assignee_id is not None:
        assignee = db.scalar(select(User).where(User.id == assignee_id))
        if (
            assignee is None
            or not assignee.is_active
            or assignee.role not in CASE_ASSIGNEE_ROLES
        ):
            raise InvalidCaseAssignee
    old_assignee_id = record.assigned_to_id
    if old_assignee_id == assignee_id:
        return get_case_response(
            db, dataset_id=dataset_id, case_id=case_id, actor=actor
        )
    record.assigned_to_id = assignee_id
    record.updated_at = utc_now()
    if old_assignee_id is None:
        event_type = "case.assignment_assigned"
    elif assignee_id is None:
        event_type = "case.assignment_removed"
    else:
        event_type = "case.assignment_reassigned"
    _audit_case(
        db,
        case_record=record,
        actor_id=actor.id,
        event_type=event_type,
        details={
            "previous_assignee_id": str(old_assignee_id) if old_assignee_id else None,
            "assigned_to_id": str(assignee_id) if assignee_id else None,
        },
    )
    try:
        db.commit()
        db.refresh(record)
    except IntegrityError as exc:
        db.rollback()
        raise CaseConflict from exc
    return _get_case_response_after_access_change(
        db, dataset_id=dataset_id, case_id=case_id
    )


def list_case_assignment_history(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    page: int,
    page_size: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    record = get_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
    assignee = (
        db.get(User, record.assigned_to_id)
        if record.assigned_to_id is not None
        else None
    )
    condition = (
        AuditLog.entity_type == "investigation_case",
        AuditLog.entity_id == case_id,
        AuditLog.event_type.in_(ASSIGNMENT_EVENTS),
    )
    total = int(db.scalar(select(func.count(AuditLog.id)).where(*condition)) or 0)
    events = db.execute(
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(*condition)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    history = []
    for event, event_actor in events:
        details = event.details or {}
        history.append(
            {
                "audit_id": event.id,
                "event_type": event.event_type,
                "previous_assignee_id": details.get("previous_assignee_id"),
                "assigned_to_id": details.get("assigned_to_id"),
                "actor": _user_summary(event_actor),
                "created_at": event.created_at,
            }
        )
    return _user_summary(assignee), history, total


def _account_snapshot(account: Account) -> dict[str, Any]:
    return {
        "account_id": str(account.id),
        "account_type": account.account_type,
        "institution_code": account.institution_code,
        "country_code": account.country_code,
        "observed_at": utc_now().isoformat(),
    }


def _version_snapshot(
    previous_snapshot: dict[str, Any] | None, current_snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Keep each prior link-time snapshot when a soft-removed link is restored."""

    if previous_snapshot is None:
        return current_snapshot
    previous = dict(previous_snapshot)
    history = previous.pop("history", [])
    return {**current_snapshot, "history": [*history, previous]}


def add_case_account(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    account_id: UUID,
    note: str | None,
) -> dict[str, Any]:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    if record.archived_at is not None:
        raise CaseConflict("Archived cases cannot be changed.")
    account = db.scalar(
        select(Account).where(
            Account.dataset_id == dataset_id,
            Account.id == account_id,
        )
    )
    if account is None:
        raise CaseResourceNotFound
    link = db.get(CaseAccount, (case_id, account_id))
    now = utc_now()
    if link is not None and link.removed_at is None:
        raise CaseConflict("Account is already linked to this case.")
    if link is None:
        link = CaseAccount(
            dataset_id=dataset_id,
            case_id=case_id,
            account_id=account_id,
            added_by_id=actor.id,
            note=note,
            evidence_snapshot=_account_snapshot(account),
            added_at=now,
        )
        db.add(link)
    else:
        link.added_by_id = actor.id
        link.note = note
        link.evidence_snapshot = _version_snapshot(
            link.evidence_snapshot, _account_snapshot(account)
        )
        link.added_at = now
        link.removed_at = None
        link.removed_by_id = None
    record.updated_at = now
    _audit_case(
        db,
        case_record=record,
        actor_id=actor.id,
        event_type="case.account_linked",
        details={"account_id": str(account_id)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CaseConflict from exc
    return {
        "dataset_id": dataset_id,
        "case_id": case_id,
        "account_id": account_id,
        "account_type": account.account_type,
        "institution_code": account.institution_code,
        "country_code": account.country_code,
        "evidence_snapshot": link.evidence_snapshot,
        "note": link.note,
        "added_by_id": link.added_by_id,
        "linked_at": link.added_at,
        "removed_at": link.removed_at,
    }


def remove_case_account(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    account_id: UUID,
    actor: User,
) -> None:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    if record.archived_at is not None:
        raise CaseConflict("Archived cases cannot be changed.")
    link = db.get(CaseAccount, (case_id, account_id))
    if link is None or link.dataset_id != dataset_id or link.removed_at is not None:
        raise CaseResourceNotFound
    now = utc_now()
    link.removed_at = now
    link.removed_by_id = actor.id
    record.updated_at = now
    _audit_case(
        db,
        case_record=record,
        actor_id=actor.id,
        event_type="case.account_unlinked",
        details={"account_id": str(account_id)},
    )
    db.commit()


def list_case_accounts(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    include_removed: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    get_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
    conditions: list[Any] = [
        CaseAccount.dataset_id == dataset_id,
        CaseAccount.case_id == case_id,
    ]
    if not include_removed:
        conditions.append(CaseAccount.removed_at.is_(None))
    total = int(
        db.scalar(select(func.count()).select_from(CaseAccount).where(*conditions)) or 0
    )
    rows = db.execute(
        select(CaseAccount, Account)
        .join(
            Account,
            (Account.dataset_id == CaseAccount.dataset_id)
            & (Account.id == CaseAccount.account_id),
        )
        .where(*conditions)
        .order_by(CaseAccount.added_at.desc(), CaseAccount.account_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        {
            "dataset_id": dataset_id,
            "case_id": case_id,
            "account_id": link.account_id,
            "account_type": account.account_type,
            "institution_code": account.institution_code,
            "country_code": account.country_code,
            "evidence_snapshot": link.evidence_snapshot,
            "note": link.note,
            "added_by_id": link.added_by_id,
            "linked_at": link.added_at,
            "removed_at": link.removed_at,
        }
        for link, account in rows
    ], total


def _finding_snapshot(db: Session, finding: DetectionFinding) -> dict[str, Any]:
    account_refs = db.execute(
        select(FindingAccount.account_id, FindingAccount.relationship_role)
        .where(
            FindingAccount.dataset_id == finding.dataset_id,
            FindingAccount.finding_id == finding.id,
        )
        .order_by(FindingAccount.account_id)
    ).all()
    transaction_refs = db.execute(
        select(FindingTransaction, Transaction)
        .join(
            Transaction,
            (Transaction.dataset_id == FindingTransaction.dataset_id)
            & (Transaction.id == FindingTransaction.transaction_id),
        )
        .where(
            FindingTransaction.dataset_id == finding.dataset_id,
            FindingTransaction.finding_id == finding.id,
        )
        .order_by(Transaction.occurred_at, Transaction.id)
        .limit(MAX_EVIDENCE_SNAPSHOT_TRANSACTIONS + 1)
    ).all()
    truncated = len(transaction_refs) > MAX_EVIDENCE_SNAPSHOT_TRANSACTIONS
    transaction_refs = transaction_refs[:MAX_EVIDENCE_SNAPSHOT_TRANSACTIONS]
    return {
        "finding_id": str(finding.id),
        "detector_name": finding.detector_name,
        "detector_version": finding.detector_version,
        "category": finding.category,
        "severity": finding.severity,
        "status": finding.status,
        "title": finding.title,
        "explanation": finding.explanation,
        "first_detected_at": finding.first_detected_at.isoformat(),
        "last_detected_at": finding.last_detected_at.isoformat(),
        "evidence": finding.evidence,
        "parameters": finding.parameters,
        "accounts": [
            {"account_id": str(account_id), "relationship_role": role}
            for account_id, role in account_refs
        ],
        "transactions": [
            {
                "transaction_id": str(transaction.id),
                "source_account_id": str(transaction.sender_account_id),
                "target_account_id": str(transaction.receiver_account_id),
                "amount": str(transaction.amount),
                "currency": transaction.currency,
                "occurred_at": transaction.occurred_at.isoformat(),
                "transaction_type": transaction.transaction_type,
                "channel": transaction.channel,
                "status": transaction.status,
                "evidence_role": link.evidence_role,
            }
            for link, transaction in transaction_refs
        ],
        "transaction_references_truncated": truncated,
        "snapshot_at": utc_now().isoformat(),
    }


def add_case_finding(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    finding_id: UUID,
    note: str | None,
) -> dict[str, Any]:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    if record.archived_at is not None:
        raise CaseConflict("Archived cases cannot be changed.")
    finding = db.scalar(
        select(DetectionFinding).where(
            DetectionFinding.dataset_id == dataset_id,
            DetectionFinding.id == finding_id,
        )
    )
    if finding is None:
        raise CaseResourceNotFound
    link = db.get(CaseFinding, (dataset_id, case_id, finding_id))
    if link is not None and link.removed_at is None:
        raise CaseConflict("Finding is already linked to this case.")
    now = utc_now()
    snapshot = _finding_snapshot(db, finding)
    if link is None:
        link = CaseFinding(
            dataset_id=dataset_id,
            case_id=case_id,
            finding_id=finding_id,
            linked_by_id=actor.id,
            linked_at=now,
            evidence_snapshot=snapshot,
            note=note,
        )
        db.add(link)
    else:
        link.linked_by_id = actor.id
        link.linked_at = now
        link.evidence_snapshot = _version_snapshot(link.evidence_snapshot, snapshot)
        link.note = note
        link.removed_at = None
        link.removed_by_id = None
    record.updated_at = now
    _audit_case(
        db,
        case_record=record,
        actor_id=actor.id,
        event_type="case.finding_linked",
        details={"finding_id": str(finding_id)},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CaseConflict from exc
    return {
        "dataset_id": dataset_id,
        "case_id": case_id,
        "finding_id": finding.id,
        "category": finding.category,
        "severity": finding.severity,
        "status": finding.status,
        "title": finding.title,
        "explanation": finding.explanation,
        "evidence_snapshot": link.evidence_snapshot,
        "note": link.note,
        "linked_by_id": link.linked_by_id,
        "linked_at": link.linked_at,
        "removed_at": link.removed_at,
    }


def remove_case_finding(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    finding_id: UUID,
    actor: User,
) -> None:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    if record.archived_at is not None:
        raise CaseConflict("Archived cases cannot be changed.")
    link = db.get(CaseFinding, (dataset_id, case_id, finding_id))
    if link is None or link.removed_at is not None:
        raise CaseResourceNotFound
    now = utc_now()
    link.removed_at = now
    link.removed_by_id = actor.id
    record.updated_at = now
    _audit_case(
        db,
        case_record=record,
        actor_id=actor.id,
        event_type="case.finding_unlinked",
        details={"finding_id": str(finding_id)},
    )
    db.commit()


def list_case_findings(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    include_removed: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    get_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
    conditions: list[Any] = [
        CaseFinding.dataset_id == dataset_id,
        CaseFinding.case_id == case_id,
    ]
    if not include_removed:
        conditions.append(CaseFinding.removed_at.is_(None))
    total = int(
        db.scalar(select(func.count()).select_from(CaseFinding).where(*conditions)) or 0
    )
    rows = db.execute(
        select(CaseFinding, DetectionFinding)
        .join(
            DetectionFinding,
            (DetectionFinding.dataset_id == CaseFinding.dataset_id)
            & (DetectionFinding.id == CaseFinding.finding_id),
        )
        .where(*conditions)
        .order_by(CaseFinding.linked_at.desc(), CaseFinding.finding_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        {
            "dataset_id": dataset_id,
            "case_id": case_id,
            "finding_id": finding.id,
            "category": finding.category,
            "severity": finding.severity,
            "status": finding.status,
            "title": finding.title,
            "explanation": finding.explanation,
            "evidence_snapshot": link.evidence_snapshot,
            "note": link.note,
            "linked_by_id": link.linked_by_id,
            "linked_at": link.linked_at,
            "removed_at": link.removed_at,
        }
        for link, finding in rows
    ], total


def create_case_note(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    content: str,
) -> dict[str, Any]:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    if record.archived_at is not None:
        raise CaseConflict("Archived cases cannot receive new notes.")
    note = CaseNote(
        id=uuid4(),
        dataset_id=dataset_id,
        case_id=case_id,
        author_id=actor.id,
        content=content,
    )
    db.add(note)
    db.flush()
    db.add(
        CaseNoteRevision(
            dataset_id=dataset_id,
            case_id=case_id,
            note_id=note.id,
            revision_number=1,
            content=content,
            edited_by_id=actor.id,
        )
    )
    record.updated_at = utc_now()
    _audit_case(
        db,
        case_record=record,
        actor_id=actor.id,
        event_type="case.note_created",
        details={"note_id": str(note.id), "revision_number": 1},
    )
    db.commit()
    db.refresh(note)
    return get_case_note(
        db, dataset_id=dataset_id, case_id=case_id, note_id=note.id, actor=actor
    )


def list_case_notes(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    include_archived: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    get_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
    conditions: list[Any] = [
        CaseNote.dataset_id == dataset_id,
        CaseNote.case_id == case_id,
    ]
    if not include_archived:
        conditions.append(CaseNote.archived_at.is_(None))
    revisions_count = (
        select(func.count(CaseNoteRevision.id))
        .where(
            CaseNoteRevision.dataset_id == CaseNote.dataset_id,
            CaseNoteRevision.case_id == CaseNote.case_id,
            CaseNoteRevision.note_id == CaseNote.id,
        )
        .correlate(CaseNote)
        .scalar_subquery()
    )
    total = int(db.scalar(select(func.count(CaseNote.id)).where(*conditions)) or 0)
    rows = db.execute(
        select(CaseNote, User, revisions_count.label("revision_count"))
        .outerjoin(User, User.id == CaseNote.author_id)
        .where(*conditions)
        .order_by(CaseNote.created_at.desc(), CaseNote.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        {
            "id": note.id,
            "dataset_id": dataset_id,
            "case_id": case_id,
            "author_id": note.author_id,
            "author": _user_summary(author),
            "content": note.content,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
            "archived_at": note.archived_at,
            "revision_count": max(int(count or 0), 1),
        }
        for note, author, count in rows
    ], total


def get_case_note(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    note_id: UUID,
    actor: User,
) -> dict[str, Any]:
    get_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
    revisions_count = (
        select(func.count(CaseNoteRevision.id))
        .where(
            CaseNoteRevision.dataset_id == CaseNote.dataset_id,
            CaseNoteRevision.case_id == CaseNote.case_id,
            CaseNoteRevision.note_id == CaseNote.id,
        )
        .correlate(CaseNote)
        .scalar_subquery()
    )
    row = db.execute(
        select(CaseNote, User, revisions_count)
        .outerjoin(User, User.id == CaseNote.author_id)
        .where(
            CaseNote.dataset_id == dataset_id,
            CaseNote.case_id == case_id,
            CaseNote.id == note_id,
        )
    ).one_or_none()
    if row is None:
        raise CaseResourceNotFound
    note, author, revision_count = row
    return {
        "id": note.id,
        "dataset_id": note.dataset_id,
        "case_id": note.case_id,
        "author_id": note.author_id,
        "author": _user_summary(author),
        "content": note.content,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "archived_at": note.archived_at,
        "revision_count": max(int(revision_count or 0), 1),
    }


def _require_note_editor(note: CaseNote, actor: User) -> None:
    if actor.role in CASE_WRITER_ROLES:
        return
    if note.author_id != actor.id:
        raise CasePermissionDenied


def update_case_note(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    note_id: UUID,
    actor: User,
    content: str,
) -> dict[str, Any]:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    note = db.scalar(
        select(CaseNote)
        .where(
            CaseNote.dataset_id == dataset_id,
            CaseNote.case_id == case_id,
            CaseNote.id == note_id,
        )
        .with_for_update()
    )
    if note is None:
        raise CaseResourceNotFound
    _require_note_editor(note, actor)
    if note.archived_at is not None or record.archived_at is not None:
        raise CaseConflict("Archived notes or cases cannot be edited.")
    if content == note.content:
        return get_case_note(
            db, dataset_id=dataset_id, case_id=case_id, note_id=note_id, actor=actor
        )
    previous_version = int(
        db.scalar(
            select(func.max(CaseNoteRevision.revision_number)).where(
                CaseNoteRevision.dataset_id == dataset_id,
                CaseNoteRevision.case_id == case_id,
                CaseNoteRevision.note_id == note_id,
            )
        )
        or 0
    )
    next_version = previous_version + 1
    note.content = content
    note.updated_at = utc_now()
    record.updated_at = note.updated_at
    db.add(
        CaseNoteRevision(
            dataset_id=dataset_id,
            case_id=case_id,
            note_id=note_id,
            revision_number=next_version,
            content=content,
            edited_by_id=actor.id,
        )
    )
    _audit_case(
        db,
        case_record=record,
        actor_id=actor.id,
        event_type="case.note_updated",
        details={"note_id": str(note.id), "revision_number": next_version},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CaseConflict from exc
    return get_case_note(
        db, dataset_id=dataset_id, case_id=case_id, note_id=note_id, actor=actor
    )


def archive_case_note(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    note_id: UUID,
    actor: User,
) -> dict[str, Any]:
    record = get_case(
        db, dataset_id=dataset_id, case_id=case_id, actor=actor, lock=True
    )
    note = db.scalar(
        select(CaseNote)
        .where(
            CaseNote.dataset_id == dataset_id,
            CaseNote.case_id == case_id,
            CaseNote.id == note_id,
        )
        .with_for_update()
    )
    if note is None:
        raise CaseResourceNotFound
    _require_note_editor(note, actor)
    if note.archived_at is None:
        note.archived_at = utc_now()
        note.updated_at = note.archived_at
        record.updated_at = note.archived_at
        _audit_case(
            db,
            case_record=record,
            actor_id=actor.id,
            event_type="case.note_archived",
            details={"note_id": str(note.id)},
        )
        db.commit()
    return get_case_note(
        db, dataset_id=dataset_id, case_id=case_id, note_id=note_id, actor=actor
    )


def list_case_note_revisions(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    note_id: UUID,
    actor: User,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    get_case_note(
        db, dataset_id=dataset_id, case_id=case_id, note_id=note_id, actor=actor
    )
    condition = (
        CaseNoteRevision.dataset_id == dataset_id,
        CaseNoteRevision.case_id == case_id,
        CaseNoteRevision.note_id == note_id,
    )
    total = int(
        db.scalar(select(func.count(CaseNoteRevision.id)).where(*condition)) or 0
    )
    rows = db.execute(
        select(CaseNoteRevision, User)
        .outerjoin(User, User.id == CaseNoteRevision.edited_by_id)
        .where(*condition)
        .order_by(CaseNoteRevision.revision_number.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        {
            "id": revision.id,
            "note_id": note_id,
            "revision_number": revision.revision_number,
            "content": revision.content,
            "edited_by_id": revision.edited_by_id,
            "edited_by": _user_summary(editor),
            "created_at": revision.created_at,
        }
        for revision, editor in rows
    ], total


SAFE_TIMELINE_KEYS = frozenset(
    {
        "dataset_id",
        "fields",
        "from_status",
        "to_status",
        "reason",
        "previous_assignee_id",
        "assigned_to_id",
        "account_id",
        "finding_id",
        "note_id",
        "revision_number",
        "archived",
    }
)


def list_case_timeline(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    get_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
    conditions = (
        AuditLog.entity_type == "investigation_case",
        AuditLog.entity_id == case_id,
        AuditLog.details["dataset_id"].as_string() == str(dataset_id),
    )
    total = int(db.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0)
    rows = db.execute(
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(*conditions)
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "actor_id": event.actor_user_id,
            "actor_name": user.display_name if user else None,
            "actor_role": user.role if user else None,
            "created_at": event.created_at,
            "metadata": {
                key: value
                for key, value in (event.details or {}).items()
                if key in SAFE_TIMELINE_KEYS
            },
        }
        for event, user in rows
    ], total


def get_case_report_records(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    item_limit: int,
) -> dict[str, Any]:
    """Load a bounded report snapshot using a fixed number of queries."""

    record = get_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
    if record.archived_at is not None:
        # Archived cases remain readable and reportable for audit retention.
        pass
    account_rows = db.execute(
        select(CaseAccount, Account)
        .join(
            Account,
            (Account.dataset_id == CaseAccount.dataset_id)
            & (Account.id == CaseAccount.account_id),
        )
        .where(
            CaseAccount.dataset_id == dataset_id,
            CaseAccount.case_id == case_id,
            CaseAccount.removed_at.is_(None),
        )
        .order_by(CaseAccount.added_at, CaseAccount.account_id)
        .limit(item_limit + 1)
    ).all()
    finding_rows = db.execute(
        select(CaseFinding, DetectionFinding)
        .join(
            DetectionFinding,
            (DetectionFinding.dataset_id == CaseFinding.dataset_id)
            & (DetectionFinding.id == CaseFinding.finding_id),
        )
        .where(
            CaseFinding.dataset_id == dataset_id,
            CaseFinding.case_id == case_id,
            CaseFinding.removed_at.is_(None),
        )
        .order_by(CaseFinding.linked_at, CaseFinding.finding_id)
        .limit(item_limit + 1)
    ).all()
    note_rows = db.execute(
        select(CaseNote, User)
        .outerjoin(User, User.id == CaseNote.author_id)
        .where(CaseNote.dataset_id == dataset_id, CaseNote.case_id == case_id)
        .order_by(CaseNote.created_at, CaseNote.id)
        .limit(item_limit + 1)
    ).all()
    timeline_rows = db.execute(
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(
            AuditLog.entity_type == "investigation_case",
            AuditLog.entity_id == case_id,
            AuditLog.details["dataset_id"].as_string() == str(dataset_id),
        )
        .order_by(AuditLog.created_at, AuditLog.id)
        .limit(item_limit + 1)
    ).all()
    if any(
        len(items) > item_limit
        for items in (account_rows, finding_rows, note_rows, timeline_rows)
    ):
        raise CaseExportLimitExceeded
    user_ids = {
        user_id
        for user_id in (record.created_by_id, record.assigned_to_id)
        if user_id is not None
    }
    users = (
        {
            user.id: user
            for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
        }
        if user_ids
        else {}
    )
    return {
        "case": record,
        "creator": users.get(record.created_by_id),
        "assignee": users.get(record.assigned_to_id),
        "accounts": account_rows,
        "findings": finding_rows,
        "notes": note_rows,
        "timeline": timeline_rows,
    }


def get_case_csv_evidence(
    db: Session,
    *,
    dataset_id: UUID,
    case_id: UUID,
    actor: User,
    row_limit: int,
) -> list[dict[str, Any]]:
    """Return explicit case evidence rows under a strict export row bound."""

    get_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
    records: list[dict[str, Any]] = []
    accounts = db.execute(
        select(CaseAccount, Account)
        .join(
            Account,
            (Account.dataset_id == CaseAccount.dataset_id)
            & (Account.id == CaseAccount.account_id),
        )
        .where(
            CaseAccount.dataset_id == dataset_id,
            CaseAccount.case_id == case_id,
            CaseAccount.removed_at.is_(None),
        )
        .order_by(CaseAccount.account_id)
        .limit(row_limit + 1)
    ).all()
    for link, account in accounts:
        records.append(
            {
                "record_type": "account",
                "account_id": account.id,
                "account_type": account.account_type,
                "institution_code": account.institution_code,
                "country_code": account.country_code,
                "evidence_role": "case_account",
                "evidence_snapshot": link.evidence_snapshot,
            }
        )
    findings = db.execute(
        select(CaseFinding, DetectionFinding)
        .join(
            DetectionFinding,
            (DetectionFinding.dataset_id == CaseFinding.dataset_id)
            & (DetectionFinding.id == CaseFinding.finding_id),
        )
        .where(
            CaseFinding.dataset_id == dataset_id,
            CaseFinding.case_id == case_id,
            CaseFinding.removed_at.is_(None),
        )
        .order_by(CaseFinding.finding_id)
        .limit(row_limit + 1)
    ).all()
    for link, finding in findings:
        records.append(
            {
                "record_type": "finding",
                "finding_id": finding.id,
                "finding_category": finding.category,
                "finding_severity": finding.severity,
                "finding_status": finding.status,
                "finding_title": finding.title,
                "evidence_role": "case_finding",
                "evidence_snapshot": link.evidence_snapshot,
            }
        )
    if len(records) > row_limit:
        raise CaseExportLimitExceeded

    transactions = db.execute(
        select(
            Transaction,
            FindingTransaction.finding_id,
            FindingTransaction.evidence_role,
            DetectionFinding.category,
            DetectionFinding.severity,
            DetectionFinding.title,
        )
        .join(
            FindingTransaction,
            (FindingTransaction.dataset_id == Transaction.dataset_id)
            & (FindingTransaction.transaction_id == Transaction.id),
        )
        .join(
            CaseFinding,
            (CaseFinding.dataset_id == FindingTransaction.dataset_id)
            & (CaseFinding.finding_id == FindingTransaction.finding_id),
        )
        .join(
            DetectionFinding,
            (DetectionFinding.dataset_id == CaseFinding.dataset_id)
            & (DetectionFinding.id == CaseFinding.finding_id),
        )
        .where(
            CaseFinding.dataset_id == dataset_id,
            CaseFinding.case_id == case_id,
            CaseFinding.removed_at.is_(None),
        )
        .order_by(Transaction.occurred_at, Transaction.id)
        .limit(row_limit + 1)
    ).all()
    alert_transactions = db.execute(
        select(
            Transaction,
            DetectionAlert.id,
            DetectionAlert.rule_code,
            DetectionAlert.severity,
            DetectionAlert.title,
        )
        .join(
            DetectionAlert,
            (DetectionAlert.dataset_id == Transaction.dataset_id)
            & (DetectionAlert.transaction_id == Transaction.id),
        )
        .join(
            CaseAlert,
            (CaseAlert.dataset_id == DetectionAlert.dataset_id)
            & (CaseAlert.alert_id == DetectionAlert.id),
        )
        .where(CaseAlert.dataset_id == dataset_id, CaseAlert.case_id == case_id)
        .order_by(Transaction.occurred_at, Transaction.id)
        .limit(row_limit + 1)
    ).all()
    if len(transactions) > row_limit or len(alert_transactions) > row_limit:
        raise CaseExportLimitExceeded
    for (
        transaction,
        finding_id,
        evidence_role,
        category,
        severity,
        title,
    ) in transactions:
        records.append(
            {
                "record_type": "transaction",
                "finding_id": finding_id,
                "transaction_id": transaction.id,
                "source_account_id": transaction.sender_account_id,
                "target_account_id": transaction.receiver_account_id,
                "amount": str(transaction.amount),
                "currency": transaction.currency,
                "occurred_at": transaction.occurred_at.isoformat(),
                "transaction_type": transaction.transaction_type,
                "channel": transaction.channel,
                "transaction_status": transaction.status,
                "finding_category": category,
                "finding_severity": severity,
                "finding_title": title,
                "evidence_role": evidence_role,
            }
        )
    for transaction, alert_id, rule_code, severity, title in alert_transactions:
        records.append(
            {
                "record_type": "alert_transaction",
                "finding_id": alert_id,
                "transaction_id": transaction.id,
                "source_account_id": transaction.sender_account_id,
                "target_account_id": transaction.receiver_account_id,
                "amount": str(transaction.amount),
                "currency": transaction.currency,
                "occurred_at": transaction.occurred_at.isoformat(),
                "transaction_type": transaction.transaction_type,
                "channel": transaction.channel,
                "transaction_status": transaction.status,
                "finding_category": rule_code,
                "finding_severity": severity,
                "finding_title": title,
                "evidence_role": "case_alert",
            }
        )
    if len(records) > row_limit:
        raise CaseExportLimitExceeded
    return records
