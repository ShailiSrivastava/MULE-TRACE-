"""Dataset-owner-scoped persistence for immutable ML registry metadata."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.observability import request_id_context
from app.ml.contracts import ModelRegistryMetadata
from app.models import AuditLog, MLModelRegistryRecord, User
from app.services.dataset_access import DatasetScopeNotFound, require_owned_dataset


class ModelRegistryConflict(RuntimeError):
    """The model name/version is already registered and is immutable."""


class ModelRegistryPersistenceError(RuntimeError):
    """Safe error raised when durable registry metadata cannot be written."""


def persist_model_metadata(
    db: Session,
    *,
    actor: User,
    metadata: ModelRegistryMetadata,
) -> MLModelRegistryRecord:
    """Persist version/configuration metadata without serializing an estimator."""

    try:
        require_owned_dataset(db, metadata.training_dataset_id, actor.id)
        existing = db.scalar(
            select(MLModelRegistryRecord.id).where(
                MLModelRegistryRecord.model_name == metadata.model_name,
                MLModelRegistryRecord.model_version == metadata.model_version,
            )
        )
        if existing is not None:
            raise ModelRegistryConflict(
                "A model name/version is immutable once registered."
            )
        record = MLModelRegistryRecord(
            model_name=metadata.model_name,
            model_version=metadata.model_version,
            feature_schema_version=metadata.feature_schema_version,
            entity_type=metadata.entity_type,
            training_dataset_id=metadata.training_dataset_id,
            training_timestamp=metadata.training_timestamp,
            training_sample_count=metadata.training_sample_count,
            feature_names=list(metadata.feature_names),
            model_parameters=metadata.model_parameters,
            preprocessing_config=metadata.preprocessing_config,
            evaluation_metrics=metadata.evaluation_metrics,
            random_seed=metadata.random_seed,
            status=metadata.status,
            created_by_id=actor.id,
        )
        db.add(record)
        db.flush()
        db.add(
            AuditLog(
                actor_user_id=actor.id,
                event_type="ml.model.registered",
                entity_type="ml_model_registry",
                entity_id=record.id,
                request_id=request_id_context.get(),
                details={
                    "dataset_id": str(metadata.training_dataset_id),
                    "model_name": metadata.model_name,
                    "model_version": metadata.model_version,
                    "feature_schema_version": metadata.feature_schema_version,
                    "entity_type": metadata.entity_type,
                    "training_sample_count": metadata.training_sample_count,
                    "status": metadata.status,
                },
            )
        )
        db.commit()
        db.refresh(record)
        return record
    except (DatasetScopeNotFound, ModelRegistryConflict):
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise ModelRegistryConflict(
            "A model name/version or registry reference conflicts with existing data."
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise ModelRegistryPersistenceError(
            "Model registry metadata could not be saved."
        ) from exc


def ensure_model_metadata(
    db: Session,
    *,
    actor: User,
    metadata: ModelRegistryMetadata,
) -> MLModelRegistryRecord:
    """Persist a model version once and accept only an identical retry snapshot."""
    require_owned_dataset(db, metadata.training_dataset_id, actor.id)
    existing = db.scalar(
        select(MLModelRegistryRecord).where(
            MLModelRegistryRecord.model_name == metadata.model_name,
            MLModelRegistryRecord.model_version == metadata.model_version,
        )
    )
    if existing is None:
        try:
            return persist_model_metadata(db, actor=actor, metadata=metadata)
        except ModelRegistryConflict:
            existing = db.scalar(
                select(MLModelRegistryRecord).where(
                    MLModelRegistryRecord.model_name == metadata.model_name,
                    MLModelRegistryRecord.model_version == metadata.model_version,
                )
            )
            if existing is None:
                raise

    expected = {
        "feature_schema_version": metadata.feature_schema_version,
        "entity_type": metadata.entity_type,
        "training_dataset_id": metadata.training_dataset_id,
        "training_timestamp": metadata.training_timestamp,
        "training_sample_count": metadata.training_sample_count,
        "feature_names": list(metadata.feature_names),
        "model_parameters": metadata.model_parameters,
        "preprocessing_config": metadata.preprocessing_config,
        "evaluation_metrics": metadata.evaluation_metrics,
        "random_seed": metadata.random_seed,
        "status": metadata.status,
        "created_by_id": actor.id,
    }
    if any(getattr(existing, field) != value for field, value in expected.items()):
        raise ModelRegistryConflict(
            "A retry produced metadata that conflicts with its immutable model version."
        )
    return existing
