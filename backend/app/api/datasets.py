"""Owner-scoped dataset lifecycle routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.datasets import (
    DatasetCreate,
    DatasetResponse,
    DatasetStatus,
    DatasetUpdate,
)
from app.schemas.pagination import PageResponse, page_response
from app.services.dataset_access import ResourceConflict
from app.services.datasets import (
    DatasetNotFound,
    create_dataset,
    get_dataset,
    list_datasets,
    update_dataset,
)

router = APIRouter(prefix="/datasets", tags=["Datasets"])


def _dataset_response(dataset, account_count: int, transaction_count: int):
    return DatasetResponse(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        source=dataset.source,
        status=dataset.status,
        is_synthetic=dataset.is_synthetic,
        metadata=dataset.metadata_json,
        account_count=account_count,
        transaction_count=transaction_count,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


@router.post(
    "",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dataset for the current user",
)
def create_user_dataset(
    payload: DatasetCreate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> DatasetResponse:
    try:
        dataset, account_count, transaction_count = create_dataset(
            db, actor=actor, fields=payload.model_dump()
        )
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409, detail="A dataset with this name already exists."
        ) from exc
    return _dataset_response(dataset, account_count, transaction_count)


@router.get(
    "",
    response_model=PageResponse[DatasetResponse],
    summary="List datasets owned by the current user",
)
def list_user_datasets(
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    dataset_status: Annotated[DatasetStatus | None, Query(alias="status")] = None,
    is_synthetic: bool | None = None,
) -> PageResponse[DatasetResponse]:
    rows, total = list_datasets(
        db,
        actor=actor,
        page=page,
        page_size=page_size,
        status=dataset_status,
        is_synthetic=is_synthetic,
    )
    return page_response(
        items=[
            _dataset_response(dataset, accounts, transactions)
            for dataset, accounts, transactions in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{dataset_id}",
    response_model=DatasetResponse,
    summary="Retrieve an owned dataset and its summary counts",
)
def read_user_dataset(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> DatasetResponse:
    try:
        dataset, account_count, transaction_count = get_dataset(
            db, dataset_id=dataset_id, actor=actor
        )
    except DatasetNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    return _dataset_response(dataset, account_count, transaction_count)


@router.patch(
    "/{dataset_id}",
    response_model=DatasetResponse,
    summary="Update permitted dataset metadata",
)
def patch_user_dataset(
    dataset_id: UUID,
    payload: DatasetUpdate,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
) -> DatasetResponse:
    try:
        dataset, account_count, transaction_count = update_dataset(
            db,
            dataset_id=dataset_id,
            actor=actor,
            fields=payload.model_dump(exclude_unset=True),
        )
    except DatasetNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409, detail="A dataset with this name already exists."
        ) from exc
    return _dataset_response(dataset, account_count, transaction_count)
