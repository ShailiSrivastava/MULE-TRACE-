"""Authenticated account routes scoped to a dataset owned by the caller."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.core.rate_limit import SensitiveWriteRateLimit
from app.models import User
from app.schemas.accounts import AccountCreate, AccountResponse, AccountUpdate
from app.schemas.pagination import PageResponse, page_response
from app.services.accounts import (
    AccountNotFound,
    create_account,
    get_account,
    list_accounts,
    update_account,
)
from app.services.dataset_access import DatasetScopeNotFound, ResourceConflict

router = APIRouter(
    prefix="/datasets/{dataset_id}/accounts",
    tags=["Accounts"],
)


def _account_response(account, transaction_count: int) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        dataset_id=account.dataset_id,
        external_id=account.external_id,
        account_type=account.account_type,
        institution_code=account.institution_code,
        country_code=account.country_code,
        metadata=account.metadata_json,
        transaction_count=transaction_count,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account in an owned dataset",
)
def create_dataset_account(
    dataset_id: UUID,
    payload: AccountCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
) -> AccountResponse:
    try:
        account, transaction_count = create_account(
            db,
            dataset_id=dataset_id,
            actor=actor,
            fields=payload.model_dump(),
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="An account with this external ID already exists in the dataset.",
        ) from exc
    return _account_response(account, transaction_count)


@router.get(
    "",
    response_model=PageResponse[AccountResponse],
    summary="List accounts in an owned dataset",
)
def list_dataset_accounts(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    account_type: Annotated[str | None, Query(max_length=50)] = None,
    country_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    external_id: Annotated[str | None, Query(max_length=160)] = None,
) -> PageResponse[AccountResponse]:
    if country_code is not None and (
        not country_code.isascii() or not country_code.isalpha()
    ):
        raise HTTPException(
            status_code=422, detail="Country code must be a two-letter code."
        )
    try:
        rows, total = list_accounts(
            db,
            dataset_id=dataset_id,
            actor=actor,
            page=page,
            page_size=page_size,
            account_type=account_type,
            country_code=country_code,
            external_id=external_id,
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    return page_response(
        items=[_account_response(account, count) for account, count in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{account_id}",
    response_model=AccountResponse,
    summary="Retrieve an account by ID",
)
def read_dataset_account(
    dataset_id: UUID,
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> AccountResponse:
    try:
        account, transaction_count = get_account(
            db, dataset_id=dataset_id, account_id=account_id, actor=actor
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found.") from exc
    return _account_response(account, transaction_count)


@router.patch(
    "/{account_id}",
    response_model=AccountResponse,
    summary="Update permitted account fields",
)
def patch_dataset_account(
    dataset_id: UUID,
    account_id: UUID,
    payload: AccountUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
) -> AccountResponse:
    try:
        account, transaction_count = update_account(
            db,
            dataset_id=dataset_id,
            account_id=account_id,
            actor=actor,
            fields=payload.model_dump(exclude_unset=True),
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found.") from exc
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="The account update conflicts with an existing record.",
        ) from exc
    return _account_response(account, transaction_count)
