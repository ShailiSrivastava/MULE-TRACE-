"""Owner-scoped feature loading; this module deliberately never queries labels."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.graph.models import (
    DEFAULT_GRAPH_LIMITS,
    GraphFilters,
    GraphLimits,
    normalize_utc,
)
from app.ml.features import FeatureBatch, extract_features
from app.services.graph import build_owned_dataset_graph


def extract_owned_dataset_features(
    db: Session,
    *,
    dataset_id: UUID,
    owner_id: UUID,
    analysis_cutoff: datetime,
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> FeatureBatch:
    """Load one bounded historical graph and extract features without labels."""

    cutoff = normalize_utc(analysis_cutoff, field_name="analysis_cutoff")
    graph = build_owned_dataset_graph(
        db,
        dataset_id=dataset_id,
        owner_id=owner_id,
        filters=GraphFilters(end_at=cutoff + timedelta(microseconds=1)),
        limits=limits,
    )
    return extract_features(graph, analysis_cutoff=cutoff)
