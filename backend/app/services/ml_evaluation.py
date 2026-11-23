"""Explicit ground-truth access isolated to evaluation workflows."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GroundTruthLabel, User
from app.services.dataset_access import require_owned_dataset


class GroundTruthConfigurationError(ValueError):
    """Evaluation label classes overlap or are not configured."""


def load_binary_ground_truth(
    db: Session,
    *,
    dataset_id: UUID,
    actor: User,
    label_scheme: str,
    positive_label_codes: set[str],
    negative_label_codes: set[str],
) -> dict[UUID, bool]:
    """Read explicitly labeled rows for evaluation; unlabeled rows stay unknown.

    This is the only ML service that reads ``GroundTruthLabel``. Feature loading,
    preprocessing, fitting, inference, and model registry code do not import it.
    """

    positives = {value.strip().lower() for value in positive_label_codes}
    negatives = {value.strip().lower() for value in negative_label_codes}
    if not label_scheme.strip() or not positives or not negatives:
        raise GroundTruthConfigurationError(
            "An evaluation scheme needs nonempty positive and negative label codes."
        )
    if positives & negatives:
        raise GroundTruthConfigurationError(
            "A label code cannot be both positive and negative."
        )
    require_owned_dataset(db, dataset_id, actor.id)
    rows = db.execute(
        select(GroundTruthLabel.transaction_id, GroundTruthLabel.label_code).where(
            GroundTruthLabel.dataset_id == dataset_id,
            GroundTruthLabel.label_scheme == label_scheme,
        )
    ).all()
    result: dict[UUID, bool] = {}
    for transaction_id, raw_code in rows:
        code = raw_code.strip().lower()
        if code in positives:
            result[transaction_id] = True
        elif code in negatives:
            result[transaction_id] = False
    return result
