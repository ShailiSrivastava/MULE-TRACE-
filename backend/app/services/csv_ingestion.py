"""Bounded, dataset-scoped, atomic CSV ingestion workflows."""

from __future__ import annotations

import csv
import json
import unicodedata
from dataclasses import dataclass
from io import TextIOWrapper
from typing import Any, BinaryIO, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.model_base import utc_now
from app.models import Account, Dataset, ImportJob, Transaction, User
from app.schemas.accounts import AccountCreate
from app.schemas.transactions import TransactionCreate
from app.services.dataset_access import (
    DatasetScopeNotFound,
    ResourceConflict,
    record_resource_audit,
    require_owned_dataset,
)

ImportKind = Literal["accounts", "transactions"]

ACCOUNT_HEADERS = {
    "external_id",
    "account_type",
    "institution_code",
    "country_code",
    "metadata_json",
}
ACCOUNT_REQUIRED_HEADERS = {"external_id"}
TRANSACTION_HEADERS = {
    "external_transaction_id",
    "sender_external_id",
    "receiver_external_id",
    "amount",
    "currency",
    "occurred_at",
    "transaction_type",
    "channel",
    "status",
    "metadata_json",
}
TRANSACTION_REQUIRED_HEADERS = {
    "external_transaction_id",
    "sender_external_id",
    "receiver_external_id",
    "amount",
    "currency",
    "occurred_at",
}


@dataclass(frozen=True)
class CsvRowIssue:
    row: int
    code: str
    message: str
    rejected: bool = True
    duplicate: bool = False


@dataclass(frozen=True)
class CsvRecord:
    row: int
    values: dict[str, str | None]


@dataclass(frozen=True)
class CsvReadResult:
    records: tuple[CsvRecord, ...]
    total_rows: int
    skipped_rows: int
    issues: tuple[CsvRowIssue, ...]
    fatal: bool = False


class InvalidCsvMetadata(ValueError):
    """Raised when metadata is malformed or uses a reserved provenance key."""


def sanitize_filename(filename: str | None) -> str:
    """Store only a safe display basename; never use a client path on disk."""

    value = unicodedata.normalize("NFKC", (filename or "").replace("\\", "/"))
    basename = value.split("/")[-1]
    cleaned = "".join(character for character in basename if character.isprintable())
    cleaned = cleaned.strip().strip(".")[:255]
    return cleaned or "upload.csv"


def _file_size(fileobj: BinaryIO) -> int:
    fileobj.seek(0, 2)
    size = fileobj.tell()
    fileobj.seek(0)
    return size


def _read_csv(fileobj: BinaryIO, *, import_type: ImportKind) -> CsvReadResult:
    fileobj.seek(0)
    text_file = TextIOWrapper(fileobj, encoding="utf-8-sig", newline="")
    issues: list[CsvRowIssue] = []
    records: list[CsvRecord] = []
    total_rows = 0
    skipped_rows = 0
    try:
        reader = csv.DictReader(text_file, strict=True)
        raw_headers = reader.fieldnames
        if not raw_headers:
            return CsvReadResult(
                (),
                0,
                0,
                (CsvRowIssue(1, "missing_header", "CSV header row is required."),),
                True,
            )

        headers = [header.strip().lower() for header in raw_headers]
        header_errors: list[CsvRowIssue] = []
        allowed = ACCOUNT_HEADERS if import_type == "accounts" else TRANSACTION_HEADERS
        required = (
            ACCOUNT_REQUIRED_HEADERS
            if import_type == "accounts"
            else TRANSACTION_REQUIRED_HEADERS
        )
        if any(not header for header in headers):
            header_errors.append(
                CsvRowIssue(1, "empty_header", "CSV headers cannot be empty.")
            )
        if len(headers) != len(set(headers)):
            header_errors.append(
                CsvRowIssue(1, "duplicate_header", "CSV contains duplicate headers.")
            )
        if required - set(headers):
            header_errors.append(
                CsvRowIssue(
                    1,
                    "missing_required_column",
                    "CSV is missing one or more required columns.",
                )
            )
        if set(headers) - allowed:
            header_errors.append(
                CsvRowIssue(
                    1,
                    "unsupported_column",
                    "CSV contains a column outside the documented canonical format.",
                )
            )
        if header_errors:
            return CsvReadResult((), 0, 0, tuple(header_errors), True)

        reader.fieldnames = headers
        row_limit_exceeded = False
        first_over_limit_row: int | None = None
        for row_number, raw_row in enumerate(reader, start=2):
            total_rows += 1
            if total_rows > settings.CSV_MAX_ROWS:
                row_limit_exceeded = True
                if first_over_limit_row is None:
                    first_over_limit_row = row_number
                continue
            if None in raw_row:
                issues.append(
                    CsvRowIssue(
                        row_number,
                        "too_many_columns",
                        "Row has more values than the CSV header.",
                    )
                )
                continue
            values = {
                key: (value.strip() if value is not None else None)
                for key, value in raw_row.items()
            }
            if not any(value for value in values.values()):
                skipped_rows += 1
                issues.append(
                    CsvRowIssue(
                        row_number,
                        "blank_row_skipped",
                        "Blank row was skipped.",
                        rejected=False,
                    )
                )
                continue
            records.append(CsvRecord(row=row_number, values=values))

        if row_limit_exceeded:
            return CsvReadResult(
                (),
                total_rows,
                0,
                (
                    CsvRowIssue(
                        first_over_limit_row or settings.CSV_MAX_ROWS + 2,
                        "row_limit_exceeded",
                        f"CSV exceeds the configured limit of {settings.CSV_MAX_ROWS} rows.",
                    ),
                ),
                True,
            )
        return CsvReadResult(tuple(records), total_rows, skipped_rows, tuple(issues))
    except (csv.Error, UnicodeDecodeError):
        return CsvReadResult(
            (),
            total_rows,
            0,
            (
                CsvRowIssue(
                    total_rows + 2,
                    "malformed_csv",
                    "CSV is malformed or is not valid UTF-8.",
                ),
            ),
            True,
        )
    finally:
        if not text_file.closed:
            text_file.detach()


def _optional(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _metadata(value: str | None) -> dict[str, Any]:
    if value is None or not value.strip():
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise InvalidCsvMetadata("metadata_json must contain a JSON object.")
    if "muletrace_import" in parsed:
        raise InvalidCsvMetadata(
            "metadata_json cannot set the reserved muletrace_import property."
        )
    return parsed


def _metadata_with_provenance(job: ImportJob, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        **metadata,
        "muletrace_import": {
            "job_id": str(job.id),
            "filename": job.original_filename,
        },
    }


def _validation_message(exc: ValidationError) -> str:
    entries = exc.errors(include_input=False, include_context=False)
    messages = [
        f"{'.'.join(str(part) for part in entry.get('loc', ())) or 'row'}: {entry['msg']}"
        for entry in entries
    ]
    return "; ".join(messages)[:500]


def _new_job(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    import_type: ImportKind,
    filename: str | None,
) -> ImportJob:
    require_owned_dataset(db, dataset_id, actor.id)
    dataset_is_synthetic = db.scalar(
        select(Dataset.is_synthetic).where(Dataset.id == dataset_id)
    )
    if dataset_is_synthetic:
        raise ResourceConflict("CSV imports cannot be mixed into a synthetic dataset.")
    job = ImportJob(
        dataset_id=dataset_id,
        created_by_id=actor.id,
        import_type=import_type,
        original_filename=sanitize_filename(filename),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _finish_job(
    db: Session,
    *,
    job: ImportJob,
    actor: User,
    status: Literal["completed", "failed"],
    total_rows: int,
    accepted_rows: int,
    rejected_rows: int,
    skipped_rows: int,
    duplicate_rows: int,
    issues: list[CsvRowIssue],
    summary: str | None = None,
) -> tuple[ImportJob, list[CsvRowIssue]]:
    job.status = status
    job.total_rows = total_rows
    job.accepted_rows = accepted_rows
    job.rejected_rows = rejected_rows
    job.skipped_rows = skipped_rows
    job.duplicate_rows = duplicate_rows
    job.error_summary = (
        {"message": summary, "row_error_count": sum(issue.rejected for issue in issues)}
        if summary or any(issue.rejected for issue in issues)
        else {}
    )
    job.completed_at = utc_now()
    record_resource_audit(
        db,
        actor_id=actor.id,
        event_type=f"dataset.import.{status}",
        entity_type="import_job",
        entity_id=job.id,
        dataset_id=job.dataset_id,
        fields=[
            "status",
            "accepted_rows",
            "rejected_rows",
            "skipped_rows",
            "duplicate_rows",
        ],
    )
    db.commit()
    db.refresh(job)
    return job, issues


def _chunked[T](values: list[T], size: int = 500):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _existing_account_ids(
    db: Session, *, dataset_id: UUID, external_ids: set[str]
) -> set[str]:
    existing: set[str] = set()
    for values in _chunked(sorted(external_ids)):
        existing.update(
            db.scalars(
                select(Account.external_id).where(
                    Account.dataset_id == dataset_id,
                    Account.external_id.in_(values),
                )
            ).all()
        )
    return existing


def _account_reference_map(
    db: Session, *, dataset_id: UUID, external_ids: set[str]
) -> dict[str, UUID]:
    reference_map: dict[str, UUID] = {}
    for values in _chunked(sorted(external_ids)):
        rows = db.execute(
            select(Account.external_id, Account.id).where(
                Account.dataset_id == dataset_id,
                Account.external_id.in_(values),
            )
        ).all()
        reference_map.update((row[0], row[1]) for row in rows)
    return reference_map


def _existing_transaction_ids(
    db: Session, *, dataset_id: UUID, external_ids: set[str]
) -> set[str]:
    existing: set[str] = set()
    for values in _chunked(sorted(external_ids)):
        existing.update(
            db.scalars(
                select(Transaction.external_transaction_id).where(
                    Transaction.dataset_id == dataset_id,
                    Transaction.external_transaction_id.in_(values),
                )
            ).all()
        )
    return existing


def _account_payloads(
    records: tuple[CsvRecord, ...],
) -> tuple[list[tuple[int, dict[str, Any]]], list[CsvRowIssue]]:
    valid: list[tuple[int, dict[str, Any]]] = []
    issues: list[CsvRowIssue] = []
    for record in records:
        values = record.values
        try:
            payload = AccountCreate.model_validate(
                {
                    "external_id": values.get("external_id"),
                    "account_type": _optional(values.get("account_type")),
                    "institution_code": _optional(values.get("institution_code")),
                    "country_code": _optional(values.get("country_code")),
                    "metadata": _metadata(values.get("metadata_json")),
                }
            )
        except (ValidationError, InvalidCsvMetadata, json.JSONDecodeError) as exc:
            message = (
                _validation_message(exc)
                if isinstance(exc, ValidationError)
                else str(exc)
                if isinstance(exc, InvalidCsvMetadata)
                else "metadata_json must contain a JSON object."
            )
            issues.append(CsvRowIssue(record.row, "invalid_account_row", message))
            continue
        valid.append((record.row, payload.model_dump()))
    return valid, issues


def _transaction_payloads(
    db: Session,
    *,
    dataset_id: UUID,
    records: tuple[CsvRecord, ...],
) -> tuple[list[tuple[int, dict[str, Any]]], list[CsvRowIssue]]:
    candidates: list[tuple[CsvRecord, dict[str, Any]]] = []
    issues: list[CsvRowIssue] = []
    account_external_ids: set[str] = set()
    for record in records:
        values = record.values
        external_transaction_id = _optional(values.get("external_transaction_id"))
        if external_transaction_id is None:
            issues.append(
                CsvRowIssue(
                    record.row,
                    "missing_external_transaction_id",
                    "external_transaction_id is required for safe retry handling.",
                )
            )
            continue
        sender = _optional(values.get("sender_external_id"))
        receiver = _optional(values.get("receiver_external_id"))
        if sender:
            account_external_ids.add(sender)
        if receiver:
            account_external_ids.add(receiver)
        try:
            data = {
                "sender_account_id": UUID(int=0),
                "receiver_account_id": UUID(int=1),
                "external_transaction_id": external_transaction_id,
                "amount": values.get("amount"),
                "currency": values.get("currency"),
                "transaction_type": _optional(values.get("transaction_type")),
                "channel": _optional(values.get("channel")),
                "status": _optional(values.get("status")),
                "occurred_at": values.get("occurred_at"),
                "metadata": _metadata(values.get("metadata_json")),
            }
            payload = TransactionCreate.model_validate(data)
        except (ValidationError, InvalidCsvMetadata, json.JSONDecodeError) as exc:
            message = (
                _validation_message(exc)
                if isinstance(exc, ValidationError)
                else str(exc)
                if isinstance(exc, InvalidCsvMetadata)
                else "metadata_json must contain a JSON object."
            )
            issues.append(CsvRowIssue(record.row, "invalid_transaction_row", message))
            continue
        candidates.append((record, payload.model_dump()))

    references = _account_reference_map(
        db, dataset_id=dataset_id, external_ids=account_external_ids
    )
    valid: list[tuple[int, dict[str, Any]]] = []
    for record, payload in candidates:
        sender_external_id = _optional(record.values.get("sender_external_id"))
        receiver_external_id = _optional(record.values.get("receiver_external_id"))
        sender_id = references.get(sender_external_id or "")
        receiver_id = references.get(receiver_external_id or "")
        if sender_id is None or receiver_id is None:
            missing_side = "Sender" if sender_id is None else "Receiver"
            issues.append(
                CsvRowIssue(
                    record.row,
                    "unknown_account",
                    f"{missing_side} account was not found in this dataset.",
                )
            )
            continue
        if sender_id == receiver_id:
            issues.append(
                CsvRowIssue(
                    record.row,
                    "same_sender_and_receiver",
                    "Sender and receiver must identify different accounts.",
                )
            )
            continue
        payload["sender_account_id"] = sender_id
        payload["receiver_account_id"] = receiver_id
        valid.append((record.row, payload))
    return valid, issues


def _deduplicate(
    valid: list[tuple[int, dict[str, Any]]],
    *,
    id_field: str,
    existing_ids: set[str],
) -> tuple[list[tuple[int, dict[str, Any]]], int, list[CsvRowIssue]]:
    new_records: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    duplicate_count = 0
    issues: list[CsvRowIssue] = []
    for row_number, payload in valid:
        external_id = payload[id_field]
        if external_id in existing_ids or external_id in seen:
            duplicate_count += 1
            issues.append(
                CsvRowIssue(
                    row_number,
                    "duplicate_skipped",
                    "Duplicate external ID was already present in this dataset or file; row skipped.",
                    rejected=False,
                    duplicate=True,
                )
            )
            continue
        seen.add(external_id)
        new_records.append((row_number, payload))
    return new_records, duplicate_count, issues


def _import_csv(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    import_type: ImportKind,
    fileobj: BinaryIO,
    filename: str | None,
) -> tuple[ImportJob, list[CsvRowIssue]]:
    job = _new_job(
        db,
        dataset_id=dataset_id,
        actor=actor,
        import_type=import_type,
        filename=filename,
    )
    if _file_size(fileobj) > settings.CSV_MAX_UPLOAD_BYTES:
        return _finish_job(
            db,
            job=job,
            actor=actor,
            status="failed",
            total_rows=0,
            accepted_rows=0,
            rejected_rows=0,
            skipped_rows=0,
            duplicate_rows=0,
            issues=[
                CsvRowIssue(
                    0,
                    "file_too_large",
                    f"Upload exceeds the configured {settings.CSV_MAX_UPLOAD_BYTES}-byte limit.",
                )
            ],
            summary="Upload size limit exceeded.",
        )

    parsed = _read_csv(fileobj, import_type=import_type)
    if parsed.fatal:
        rejected_rows = (
            parsed.total_rows
            if any(
                issue.code in {"row_limit_exceeded", "malformed_csv"}
                for issue in parsed.issues
            )
            else 0
        )
        return _finish_job(
            db,
            job=job,
            actor=actor,
            status="failed",
            total_rows=parsed.total_rows,
            accepted_rows=0,
            rejected_rows=rejected_rows,
            skipped_rows=0,
            duplicate_rows=0,
            issues=list(parsed.issues),
            summary=parsed.issues[0].message,
        )

    if import_type == "accounts":
        valid, validation_issues = _account_payloads(parsed.records)
        existing = _existing_account_ids(
            db,
            dataset_id=dataset_id,
            external_ids={payload["external_id"] for _, payload in valid},
        )
        new_rows, duplicate_count, duplicate_issues = _deduplicate(
            valid, id_field="external_id", existing_ids=existing
        )
    else:
        valid, validation_issues = _transaction_payloads(
            db, dataset_id=dataset_id, records=parsed.records
        )
        existing = _existing_transaction_ids(
            db,
            dataset_id=dataset_id,
            external_ids={payload["external_transaction_id"] for _, payload in valid},
        )
        new_rows, duplicate_count, duplicate_issues = _deduplicate(
            valid, id_field="external_transaction_id", existing_ids=existing
        )

    issues = [*parsed.issues, *validation_issues, *duplicate_issues]
    rejected_count = sum(
        issue.rejected for issue in [*parsed.issues, *validation_issues]
    )
    skipped_count = parsed.skipped_rows + duplicate_count
    if rejected_count:
        # One invalid row rejects the entire batch. Valid non-duplicate rows are
        # counted as skipped because the atomic batch is rolled back as a unit.
        skipped_count += len(new_rows)
        issues.append(
            CsvRowIssue(
                0,
                "atomic_batch_rolled_back",
                "No data rows were committed because this atomic batch contains invalid rows.",
                rejected=False,
            )
        )
        return _finish_job(
            db,
            job=job,
            actor=actor,
            status="failed",
            total_rows=parsed.total_rows,
            accepted_rows=0,
            rejected_rows=rejected_count,
            skipped_rows=skipped_count,
            duplicate_rows=duplicate_count,
            issues=issues,
            summary="Atomic batch rejected because one or more data rows are invalid.",
        )

    try:
        if import_type == "accounts":
            db.add_all(
                Account(
                    dataset_id=dataset_id,
                    external_id=payload["external_id"],
                    account_type=payload.get("account_type"),
                    institution_code=payload.get("institution_code"),
                    country_code=payload.get("country_code"),
                    metadata_json=_metadata_with_provenance(
                        job, payload.get("metadata", {})
                    ),
                )
                for _, payload in new_rows
            )
        else:
            db.add_all(
                Transaction(
                    dataset_id=dataset_id,
                    sender_account_id=payload["sender_account_id"],
                    receiver_account_id=payload["receiver_account_id"],
                    external_transaction_id=payload["external_transaction_id"],
                    amount=payload["amount"],
                    currency=payload["currency"],
                    transaction_type=payload.get("transaction_type"),
                    channel=payload.get("channel"),
                    status=payload.get("status"),
                    occurred_at=payload["occurred_at"],
                    metadata_json=_metadata_with_provenance(
                        job, payload.get("metadata", {})
                    ),
                )
                for _, payload in new_rows
            )
        db.flush()
        return _finish_job(
            db,
            job=job,
            actor=actor,
            status="completed",
            total_rows=parsed.total_rows,
            accepted_rows=len(new_rows),
            rejected_rows=0,
            skipped_rows=skipped_count,
            duplicate_rows=duplicate_count,
            issues=issues,
        )
    except IntegrityError:
        db.rollback()
        job = db.scalar(select(ImportJob).where(ImportJob.id == job.id))
        if job is None:
            raise RuntimeError("Import job disappeared during transactional rollback.")
        conflict_issues = [
            *issues,
            CsvRowIssue(
                0,
                "concurrent_conflict",
                "The batch conflicted with a concurrent dataset write; no data rows were committed.",
            ),
        ]
        return _finish_job(
            db,
            job=job,
            actor=actor,
            status="failed",
            total_rows=parsed.total_rows,
            accepted_rows=0,
            rejected_rows=len(new_rows),
            skipped_rows=skipped_count,
            duplicate_rows=duplicate_count,
            issues=conflict_issues,
            summary="Atomic batch rolled back because of a database integrity conflict.",
        )


def import_accounts_csv(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    fileobj: BinaryIO,
    filename: str | None,
) -> tuple[ImportJob, list[CsvRowIssue]]:
    return _import_csv(
        db,
        dataset_id=dataset_id,
        actor=actor,
        import_type="accounts",
        fileobj=fileobj,
        filename=filename,
    )


def import_transactions_csv(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    fileobj: BinaryIO,
    filename: str | None,
) -> tuple[ImportJob, list[CsvRowIssue]]:
    return _import_csv(
        db,
        dataset_id=dataset_id,
        actor=actor,
        import_type="transactions",
        fileobj=fileobj,
        filename=filename,
    )


def get_import_job(
    db: Session,
    *,
    dataset_id: UUID,
    import_job_id: UUID,
    actor: User,
) -> ImportJob:
    require_owned_dataset(db, dataset_id, actor.id)
    job = db.scalar(
        select(ImportJob).where(
            ImportJob.dataset_id == dataset_id,
            ImportJob.id == import_job_id,
        )
    )
    if job is None:
        raise DatasetScopeNotFound
    return job


def list_import_jobs(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    page: int,
    page_size: int,
    status: str | None = None,
) -> tuple[list[ImportJob], int]:
    require_owned_dataset(db, dataset_id, actor.id)
    filters = [ImportJob.dataset_id == dataset_id]
    if status is not None:
        filters.append(ImportJob.status == status)
    total = (
        db.scalar(select(func.count(ImportJob.id)).where(*filters))
        or 0
    )
    jobs = db.scalars(
        select(ImportJob)
        .where(*filters)
        .order_by(ImportJob.created_at.desc(), ImportJob.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(jobs), int(total)
