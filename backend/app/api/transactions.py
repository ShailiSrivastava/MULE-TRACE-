"""Authenticated transaction routes scoped to a dataset owned by the caller."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.pagination import PageResponse, page_response
from app.schemas.transactions import (
    SortDirection,
    TransactionCreate,
    TransactionResponse,
    TransactionSortField,
    TransactionUpdate,
)
from app.services.dataset_access import DatasetScopeNotFound, ResourceConflict
from app.services.transactions import (
    AccountReferenceMismatch,
    TransactionNotFound,
    create_transaction,
    get_transaction,
    list_transactions,
    update_transaction,
)

router = APIRouter(
    prefix="/datasets/{dataset_id}/transactions",
    tags=["Transactions"],
)


def _transaction_response(transaction) -> TransactionResponse:
    return TransactionResponse(
        id=transaction.id,
        dataset_id=transaction.dataset_id,
        sender_account_id=transaction.sender_account_id,
        receiver_account_id=transaction.receiver_account_id,
        external_transaction_id=transaction.external_transaction_id,
        amount=transaction.amount,
        currency=transaction.currency,
        transaction_type=transaction.transaction_type,
        channel=transaction.channel,
        status=transaction.status,
        occurred_at=transaction.occurred_at,
        metadata=transaction.metadata_json,
        created_at=transaction.created_at,
    )


def _normalize_filter_timestamp(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail=f"{name} must include a timezone offset.",
        )
    return value.astimezone(UTC)


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a transaction between accounts in the dataset",
)
def create_dataset_transaction(
    dataset_id: UUID,
    payload: TransactionCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> TransactionResponse:
    try:
        transaction = create_transaction(
            db,
            dataset_id=dataset_id,
            actor=actor,
            fields=payload.model_dump(),
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except AccountReferenceMismatch as exc:
        raise HTTPException(
            status_code=422,
            detail="Sender and receiver accounts must belong to this dataset.",
        ) from exc
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="The transaction conflicts with an existing record.",
        ) from exc
    return _transaction_response(transaction)


@router.get(
    "",
    response_model=PageResponse[TransactionResponse],
    summary="List and filter transactions in an owned dataset",
)
def list_dataset_transactions(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    account_id: UUID | None = None,
    sender_account_id: UUID | None = None,
    receiver_account_id: UUID | None = None,
    min_amount: Annotated[
        Decimal | None, Query(gt=0, max_digits=20, decimal_places=6)
    ] = None,
    max_amount: Annotated[
        Decimal | None, Query(gt=0, max_digits=20, decimal_places=6)
    ] = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sort_by: TransactionSortField = "occurred_at",
    sort_order: SortDirection = "desc",
) -> PageResponse[TransactionResponse]:
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(
            status_code=422, detail="min_amount cannot exceed max_amount."
        )
    start_at = _normalize_filter_timestamp(start_at, "start_at")
    end_at = _normalize_filter_timestamp(end_at, "end_at")
    if start_at is not None and end_at is not None and start_at > end_at:
        raise HTTPException(status_code=422, detail="start_at cannot exceed end_at.")
    if currency is not None and (not currency.isascii() or not currency.isalpha()):
        raise HTTPException(
            status_code=422, detail="Currency must be a three-letter code."
        )

    try:
        transactions, total = list_transactions(
            db,
            dataset_id=dataset_id,
            actor=actor,
            page=page,
            page_size=page_size,
            account_id=account_id,
            sender_account_id=sender_account_id,
            receiver_account_id=receiver_account_id,
            min_amount=min_amount,
            max_amount=max_amount,
            currency=currency,
            start_at=start_at,
            end_at=end_at,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    return page_response(
        items=[_transaction_response(transaction) for transaction in transactions],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Retrieve a transaction by ID",
)
def read_dataset_transaction(
    dataset_id: UUID,
    transaction_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> TransactionResponse:
    try:
        transaction = get_transaction(
            db, dataset_id=dataset_id, transaction_id=transaction_id, actor=actor
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except TransactionNotFound as exc:
        raise HTTPException(status_code=404, detail="Transaction not found.") from exc
    return _transaction_response(transaction)


@router.patch(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Update permitted transaction fields",
)
def patch_dataset_transaction(
    dataset_id: UUID,
    transaction_id: UUID,
    payload: TransactionUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> TransactionResponse:
    try:
        transaction = update_transaction(
            db,
            dataset_id=dataset_id,
            transaction_id=transaction_id,
            actor=actor,
            fields=payload.model_dump(exclude_unset=True),
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except TransactionNotFound as exc:
        raise HTTPException(status_code=404, detail="Transaction not found.") from exc
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="The transaction update conflicts with an existing record.",
        ) from exc
    return _transaction_response(transaction)
