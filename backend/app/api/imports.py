"""Owner-scoped CSV upload and import tracking routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.core.rate_limit import CsvUploadRateLimit
from app.models import ImportJob, User
from app.schemas.imports import CsvRowError, ImportJobResponse, ImportResult
from app.schemas.pagination import PageResponse, page_response
from app.services.csv_ingestion import (
    CsvRowIssue,
    get_import_job,
    import_accounts_csv,
    import_transactions_csv,
    list_import_jobs,
)
from app.services.dataset_access import DatasetScopeNotFound, ResourceConflict

router = APIRouter(
    prefix="/datasets/{dataset_id}/imports",
    tags=["CSV Imports"],
)


def _import_result(job: ImportJob, issues: list[CsvRowIssue]) -> ImportResult:
    base = ImportJobResponse.model_validate(job).model_dump()
    return ImportResult(
        **base,
        row_errors=[
            CsvRowError(row=issue.row, code=issue.code, message=issue.message)
            for issue in issues
        ],
    )


@router.post(
    "/accounts",
    response_model=ImportResult,
    summary="Import account rows from a canonical CSV file",
    description=(
        "Processes the upload synchronously and atomically. Duplicate external IDs "
        "are skipped for safe retries; any invalid row rolls back all otherwise-valid "
        "new rows in that file."
    ),
)
def import_accounts(
    dataset_id: UUID,
    file: Annotated[UploadFile, File(description="Canonical accounts CSV")],
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: CsvUploadRateLimit,
) -> ImportResult:
    try:
        job, issues = import_accounts_csv(
            db,
            dataset_id=dataset_id,
            actor=actor,
            fileobj=file.file,
            filename=file.filename,
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="CSV import cannot be applied to this dataset.",
        ) from exc
    return _import_result(job, issues)


@router.post(
    "/transactions",
    response_model=ImportResult,
    summary="Import transaction rows from a canonical CSV file",
    description=(
        "Sender and receiver external IDs must resolve to accounts in the selected "
        "dataset. The whole file is committed atomically; duplicate transaction IDs "
        "are skipped for safe retries."
    ),
)
def import_transactions(
    dataset_id: UUID,
    file: Annotated[UploadFile, File(description="Canonical transactions CSV")],
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: CsvUploadRateLimit,
) -> ImportResult:
    try:
        job, issues = import_transactions_csv(
            db,
            dataset_id=dataset_id,
            actor=actor,
            fileobj=file.file,
            filename=file.filename,
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="CSV import cannot be applied to this dataset.",
        ) from exc
    return _import_result(job, issues)


@router.get(
    "",
    response_model=PageResponse[ImportJobResponse],
    summary="List import jobs for an owned dataset",
)
def list_dataset_imports(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    status: Annotated[str | None, Query(pattern="^(pending|completed|failed)$")] = None,
) -> PageResponse[ImportJobResponse]:
    try:
        jobs, total = list_import_jobs(
            db,
            dataset_id=dataset_id,
            actor=actor,
            page=page,
            page_size=page_size,
            status=status,
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    return page_response(
        items=[ImportJobResponse.model_validate(job) for job in jobs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{import_job_id}",
    response_model=ImportJobResponse,
    summary="Retrieve an import job for an owned dataset",
)
def read_dataset_import(
    dataset_id: UUID,
    import_job_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> ImportJobResponse:
    try:
        job = get_import_job(
            db,
            dataset_id=dataset_id,
            import_job_id=import_job_id,
            actor=actor,
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Import job not found.") from exc
    return ImportJobResponse.model_validate(job)
