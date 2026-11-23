"""Case management routes for scoped financial crime investigations."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user, require_roles
from app.core.database import get_db
from app.core.rate_limit import CaseExportRateLimit, SensitiveWriteRateLimit
from app.models import User, UserRole
from app.schemas.cases import (
    CaseAccountLinkCreate,
    CaseAccountLinkResponse,
    CaseAssignmentHistoryItem,
    CaseAssignmentsResponse,
    CaseAssignmentUpdate,
    CaseCreate,
    CaseFindingLinkCreate,
    CaseFindingLinkResponse,
    CaseNoteCreate,
    CaseNoteResponse,
    CaseNoteRevisionResponse,
    CaseNoteUpdate,
    CaseResponse,
    CaseTimelineEventResponse,
    CaseUpdate,
)
from app.schemas.pagination import PageResponse, page_response
from app.services.case_reports import render_case_csv, render_case_pdf
from app.services.cases import (
    CaseConflict,
    CaseExportLimitExceeded,
    CaseNotFound,
    CasePermissionDenied,
    CaseResourceNotFound,
    InvalidCaseAssignee,
    InvalidCaseTransition,
    add_case_account,
    add_case_finding,
    archive_case,
    archive_case_note,
    create_case,
    create_case_note,
    get_case_csv_evidence,
    get_case_note,
    get_case_report_records,
    get_case_response,
    list_case_accounts,
    list_case_assignment_history,
    list_case_findings,
    list_case_note_revisions,
    list_case_notes,
    list_case_timeline,
    list_cases,
    remove_case_account,
    remove_case_finding,
    set_case_assignee,
    update_case,
    update_case_note,
)
from app.services.dataset_access import DatasetScopeNotFound

router = APIRouter(
    prefix="/datasets/{dataset_id}/cases",
    tags=["Investigation Cases"],
)
case_writer = require_roles(UserRole.INVESTIGATOR, UserRole.ADMIN)
MAX_PDF_ITEMS_PER_SECTION = 250
MAX_CSV_ROWS = 5_000


def _raise_case_error(exc: Exception) -> None:
    if isinstance(exc, (DatasetScopeNotFound, CaseNotFound)):
        raise HTTPException(
            status_code=404, detail="Case or dataset not found."
        ) from exc
    if isinstance(exc, CaseResourceNotFound):
        raise HTTPException(
            status_code=404,
            detail="The requested resource was not found in this dataset.",
        ) from exc
    if isinstance(exc, CasePermissionDenied):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to change this case note.",
        ) from exc
    if isinstance(exc, InvalidCaseAssignee):
        raise HTTPException(
            status_code=422,
            detail="Assignee must be an active investigator or administrator.",
        ) from exc
    if isinstance(exc, InvalidCaseTransition):
        raise HTTPException(
            status_code=409,
            detail="The requested case status transition is not allowed.",
        ) from exc
    if isinstance(exc, CaseConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, CaseExportLimitExceeded):
        raise HTTPException(
            status_code=413,
            detail="The case evidence exceeds the bounded export limit.",
        ) from exc
    raise exc


@router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an investigation case in an owned dataset",
)
def create_dataset_case(
    dataset_id: UUID,
    payload: CaseCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseResponse:
    try:
        result = create_case(
            db,
            dataset_id=dataset_id,
            actor=actor,
            fields=payload.model_dump(),
        )
    except (DatasetScopeNotFound, CaseConflict) as exc:
        _raise_case_error(exc)
    return CaseResponse(**result)


@router.get(
    "",
    response_model=PageResponse[CaseResponse],
    summary="List cases accessible to the dataset owner or assignee",
)
def list_dataset_cases(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    case_status: Annotated[
        Literal["open", "in_review", "resolved", "closed"] | None,
        Query(alias="status"),
    ] = None,
    priority: Literal["low", "medium", "high", "urgent"] | None = None,
    category: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    assigned_to_id: UUID | None = None,
    unassigned: bool = False,
    include_archived: bool = False,
    sort_by: Literal[
        "created_at", "updated_at", "opened_at", "status", "priority", "title"
    ] = "updated_at",
    sort_order: Literal["asc", "desc"] = "desc",
) -> PageResponse[CaseResponse]:
    if assigned_to_id is not None and unassigned:
        raise HTTPException(
            status_code=422,
            detail="assigned_to_id and unassigned cannot be used together.",
        )
    try:
        rows, total = list_cases(
            db,
            dataset_id=dataset_id,
            actor=actor,
            page=page,
            page_size=page_size,
            status=case_status,
            priority=priority,
            category=category,
            assigned_to_id=assigned_to_id,
            unassigned=unassigned,
            include_archived=include_archived,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except DatasetScopeNotFound as exc:
        _raise_case_error(exc)
    return page_response(
        items=[CaseResponse(**row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{case_id}", response_model=CaseResponse, summary="Read a case")
def read_dataset_case(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> CaseResponse:
    try:
        return CaseResponse(
            **get_case_response(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
        )
    except CaseNotFound as exc:
        _raise_case_error(exc)


@router.patch(
    "/{case_id}",
    response_model=CaseResponse,
    summary="Update case details or lifecycle status",
)
def patch_dataset_case(
    dataset_id: UUID,
    case_id: UUID,
    payload: CaseUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(case_writer)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseResponse:
    try:
        result = update_case(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            fields=payload.model_dump(exclude_unset=True),
        )
    except (CaseNotFound, CaseConflict, InvalidCaseTransition) as exc:
        _raise_case_error(exc)
    return CaseResponse(**result)


@router.delete(
    "/{case_id}",
    response_model=CaseResponse,
    summary="Archive a case without deleting its evidence",
)
def delete_dataset_case(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(case_writer)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseResponse:
    try:
        return CaseResponse(
            **archive_case(db, dataset_id=dataset_id, case_id=case_id, actor=actor)
        )
    except (CaseNotFound, CaseConflict) as exc:
        _raise_case_error(exc)


@router.patch(
    "/{case_id}/assignment",
    response_model=CaseResponse,
    summary="Assign, reassign, or remove a case investigator",
)
def patch_case_assignment(
    dataset_id: UUID,
    case_id: UUID,
    payload: CaseAssignmentUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(case_writer)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseResponse:
    try:
        result = set_case_assignee(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            assignee_id=payload.assigned_to_id,
        )
    except (CaseNotFound, CaseConflict, InvalidCaseAssignee) as exc:
        _raise_case_error(exc)
    return CaseResponse(**result)


@router.get(
    "/{case_id}/assignments",
    response_model=CaseAssignmentsResponse,
    summary="Read current assignment and assignment history",
)
def read_case_assignments(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> CaseAssignmentsResponse:
    try:
        current, history, total = list_case_assignment_history(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            page=page,
            page_size=page_size,
        )
    except CaseNotFound as exc:
        _raise_case_error(exc)
    return CaseAssignmentsResponse(
        case_id=case_id,
        current_assignee=current,
        history=page_response(
            items=[CaseAssignmentHistoryItem(**item) for item in history],
            total=total,
            page=page,
            page_size=page_size,
        ),
    )


@router.get(
    "/{case_id}/accounts",
    response_model=PageResponse[CaseAccountLinkResponse],
    summary="List accounts linked to a case",
)
def read_case_accounts(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    include_removed: bool = False,
) -> PageResponse[CaseAccountLinkResponse]:
    try:
        rows, total = list_case_accounts(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            page=page,
            page_size=page_size,
            include_removed=include_removed,
        )
    except CaseNotFound as exc:
        _raise_case_error(exc)
    return page_response(
        items=[CaseAccountLinkResponse(**row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{case_id}/accounts",
    response_model=CaseAccountLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link an account to a case",
)
def create_case_account_link(
    dataset_id: UUID,
    case_id: UUID,
    payload: CaseAccountLinkCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(case_writer)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseAccountLinkResponse:
    try:
        result = add_case_account(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            account_id=payload.account_id,
            note=payload.note,
        )
    except (CaseNotFound, CaseResourceNotFound, CaseConflict) as exc:
        _raise_case_error(exc)
    return CaseAccountLinkResponse(**result)


@router.delete(
    "/{case_id}/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink an account while retaining the case history",
)
def delete_case_account_link(
    dataset_id: UUID,
    case_id: UUID,
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(case_writer)],
    _rate_limit: SensitiveWriteRateLimit,
) -> Response:
    try:
        remove_case_account(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            account_id=account_id,
            actor=actor,
        )
    except (CaseNotFound, CaseResourceNotFound, CaseConflict) as exc:
        _raise_case_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{case_id}/findings",
    response_model=PageResponse[CaseFindingLinkResponse],
    summary="List findings linked to a case",
)
def read_case_findings(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    include_removed: bool = False,
) -> PageResponse[CaseFindingLinkResponse]:
    try:
        rows, total = list_case_findings(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            page=page,
            page_size=page_size,
            include_removed=include_removed,
        )
    except CaseNotFound as exc:
        _raise_case_error(exc)
    return page_response(
        items=[CaseFindingLinkResponse(**row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{case_id}/findings",
    response_model=CaseFindingLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link a detection finding to a case",
)
def create_case_finding_link(
    dataset_id: UUID,
    case_id: UUID,
    payload: CaseFindingLinkCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(case_writer)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseFindingLinkResponse:
    try:
        result = add_case_finding(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            finding_id=payload.finding_id,
            note=payload.note,
        )
    except (CaseNotFound, CaseResourceNotFound, CaseConflict) as exc:
        _raise_case_error(exc)
    return CaseFindingLinkResponse(**result)


@router.delete(
    "/{case_id}/findings/{finding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a finding while retaining its case evidence snapshot",
)
def delete_case_finding_link(
    dataset_id: UUID,
    case_id: UUID,
    finding_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(case_writer)],
    _rate_limit: SensitiveWriteRateLimit,
) -> Response:
    try:
        remove_case_finding(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            finding_id=finding_id,
            actor=actor,
        )
    except (CaseNotFound, CaseResourceNotFound, CaseConflict) as exc:
        _raise_case_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{case_id}/notes",
    response_model=PageResponse[CaseNoteResponse],
    summary="List investigation notes",
)
def read_case_notes(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    include_archived: bool = False,
) -> PageResponse[CaseNoteResponse]:
    try:
        rows, total = list_case_notes(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            page=page,
            page_size=page_size,
            include_archived=include_archived,
        )
    except CaseNotFound as exc:
        _raise_case_error(exc)
    return page_response(
        items=[CaseNoteResponse(**row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{case_id}/notes",
    response_model=CaseNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an investigation note",
)
def create_dataset_case_note(
    dataset_id: UUID,
    case_id: UUID,
    payload: CaseNoteCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseNoteResponse:
    try:
        return CaseNoteResponse(
            **create_case_note(
                db,
                dataset_id=dataset_id,
                case_id=case_id,
                actor=actor,
                content=payload.content,
            )
        )
    except (CaseNotFound, CaseConflict) as exc:
        _raise_case_error(exc)


@router.get(
    "/{case_id}/notes/{note_id}",
    response_model=CaseNoteResponse,
    summary="Read a retained case note",
)
def read_dataset_case_note(
    dataset_id: UUID,
    case_id: UUID,
    note_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> CaseNoteResponse:
    try:
        return CaseNoteResponse(
            **get_case_note(
                db,
                dataset_id=dataset_id,
                case_id=case_id,
                note_id=note_id,
                actor=actor,
            )
        )
    except (CaseNotFound, CaseResourceNotFound) as exc:
        _raise_case_error(exc)


@router.patch(
    "/{case_id}/notes/{note_id}",
    response_model=CaseNoteResponse,
    summary="Edit a note and retain its previous versions",
)
def patch_dataset_case_note(
    dataset_id: UUID,
    case_id: UUID,
    note_id: UUID,
    payload: CaseNoteUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseNoteResponse:
    try:
        result = update_case_note(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            note_id=note_id,
            actor=actor,
            content=payload.content,
        )
    except (
        CaseNotFound,
        CaseResourceNotFound,
        CasePermissionDenied,
        CaseConflict,
    ) as exc:
        _raise_case_error(exc)
    return CaseNoteResponse(**result)


@router.delete(
    "/{case_id}/notes/{note_id}",
    response_model=CaseNoteResponse,
    summary="Archive a note without deleting its history",
)
def delete_dataset_case_note(
    dataset_id: UUID,
    case_id: UUID,
    note_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
) -> CaseNoteResponse:
    try:
        result = archive_case_note(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            note_id=note_id,
            actor=actor,
        )
    except (
        CaseNotFound,
        CaseResourceNotFound,
        CasePermissionDenied,
    ) as exc:
        _raise_case_error(exc)
    return CaseNoteResponse(**result)


@router.get(
    "/{case_id}/notes/{note_id}/history",
    response_model=PageResponse[CaseNoteRevisionResponse],
    summary="List immutable note versions",
)
def read_case_note_history(
    dataset_id: UUID,
    case_id: UUID,
    note_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PageResponse[CaseNoteRevisionResponse]:
    try:
        rows, total = list_case_note_revisions(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            note_id=note_id,
            actor=actor,
            page=page,
            page_size=page_size,
        )
    except (CaseNotFound, CaseResourceNotFound) as exc:
        _raise_case_error(exc)
    return page_response(
        items=[CaseNoteRevisionResponse(**row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{case_id}/timeline",
    response_model=PageResponse[CaseTimelineEventResponse],
    summary="Read the chronological case audit timeline",
)
def read_case_timeline(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PageResponse[CaseTimelineEventResponse]:
    try:
        rows, total = list_case_timeline(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            page=page,
            page_size=page_size,
        )
    except CaseNotFound as exc:
        _raise_case_error(exc)
    return page_response(
        items=[CaseTimelineEventResponse(**row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{case_id}/reports/investigation.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    summary="Generate a bounded investigation PDF report",
)
def download_case_pdf_report(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: CaseExportRateLimit,
) -> Response:
    try:
        records = get_case_report_records(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            item_limit=MAX_PDF_ITEMS_PER_SECTION,
        )
        content = render_case_pdf(records)
    except (CaseNotFound, CaseExportLimitExceeded) as exc:
        _raise_case_error(exc)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="case-{case_id}.pdf"'},
    )


@router.get(
    "/{case_id}/exports/evidence.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
    summary="Export bounded case evidence as CSV",
)
def download_case_evidence_csv(
    dataset_id: UUID,
    case_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: CaseExportRateLimit,
    row_limit: Annotated[int, Query(alias="limit", ge=1, le=MAX_CSV_ROWS)] = 1_000,
) -> Response:
    try:
        evidence = get_case_csv_evidence(
            db,
            dataset_id=dataset_id,
            case_id=case_id,
            actor=actor,
            row_limit=row_limit,
        )
        content = render_case_csv(
            case_id=str(case_id), dataset_id=str(dataset_id), evidence_rows=evidence
        )
    except (CaseNotFound, CaseExportLimitExceeded) as exc:
        _raise_case_error(exc)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="case-{case_id}-evidence.csv"'
        },
    )
