"""Synchronous synthetic dataset generation endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.core.rate_limit import SensitiveWriteRateLimit
from app.models import User
from app.schemas.synthetic import (
    SyntheticGenerationRequest,
    SyntheticGenerationResponse,
)
from app.services.dataset_access import DatasetScopeNotFound, ResourceConflict
from app.services.synthetic_data import generate_dataset_data

router = APIRouter(tags=["Synthetic Data"])


@router.post(
    "/datasets/{dataset_id}/synthetic-data",
    response_model=SyntheticGenerationResponse,
    status_code=201,
    summary="Generate deterministic synthetic accounts and transactions",
    description=(
        "Creates synthetic records in an empty owned dataset. Synthetic ground-truth "
        "labels are stored separately from detection alerts and do not represent "
        "proven financial crime."
    ),
)
def generate_synthetic_dataset(
    dataset_id: UUID,
    payload: SyntheticGenerationRequest,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    _rate_limit: SensitiveWriteRateLimit,
) -> SyntheticGenerationResponse:
    try:
        return SyntheticGenerationResponse.model_validate(
            generate_dataset_data(
                db,
                dataset_id=dataset_id,
                actor=actor,
                request=payload,
            )
        )
    except DatasetScopeNotFound as exc:
        raise HTTPException(status_code=404, detail="Dataset not found.") from exc
    except ResourceConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="Synthetic generation requires an empty dataset.",
        ) from exc
