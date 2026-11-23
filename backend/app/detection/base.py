"""Shared detector protocol and deterministic graph utilities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel

from app.detection.models import DetectionFinding, DetectorSeverity, create_finding
from app.graph.builder import TransactionGraph
from app.graph.models import normalize_utc

DETECTOR_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class DetectorOutput:
    findings: tuple[DetectionFinding, ...]
    statistics: dict[str, int | bool | str]


class Detector(Protocol):
    name: str
    config_key: str
    version: str

    def detect(
        self,
        graph: TransactionGraph,
        *,
        dataset_id: UUID | None,
        config: BaseModel,
    ) -> DetectorOutput: ...


def graph_dataset_id(graph: TransactionGraph, requested: UUID | None) -> UUID | None:
    raw = graph.graph.get("dataset_id")
    graph_id = UUID(str(raw)) if raw is not None else None
    if requested is not None and graph_id is not None and requested != graph_id:
        raise ValueError("Requested dataset ID does not match the graph dataset.")
    return requested or graph_id


def edge_time(attributes: dict[str, Any]) -> datetime:
    return normalize_utc(attributes["occurred_at"], field_name="occurred_at")


def edge_id(key: Any, attributes: dict[str, Any]) -> UUID:
    value = attributes.get("transaction_id", key)
    return value if isinstance(value, UUID) else UUID(str(value))


def edge_sort_key(
    edge: tuple[Any, Any, Any, dict[str, Any]],
) -> tuple[str, str, str, str]:
    source, target, key, attributes = edge
    return (
        edge_time(attributes).isoformat(),
        str(edge_id(key, attributes)),
        str(source),
        str(target),
    )


def sorted_edges(graph: TransactionGraph) -> list[tuple[Any, Any, Any, dict[str, Any]]]:
    return sorted(graph.edges(keys=True, data=True), key=edge_sort_key)


def amount_string(value: Decimal) -> str:
    return format(value, "f")


def iso_utc(value: datetime) -> str:
    return edge_time({"occurred_at": value}).isoformat().replace("+00:00", "Z")


def currency_totals(edges: Iterable[dict[str, Any]]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for attributes in edges:
        currency = str(attributes["currency"]).upper()
        totals[currency] = totals.get(currency, Decimal(0)) + attributes["amount"]
    return dict(sorted(totals.items()))


def parameters_json(config: BaseModel) -> dict[str, Any]:
    return config.model_dump(mode="json", exclude={"enabled"})


def create_detector_finding(
    *,
    detector_name: str,
    detector_version: str,
    category: str,
    severity: DetectorSeverity,
    title: str,
    explanation: str,
    dataset_id: UUID | None,
    account_ids: Iterable[UUID],
    transaction_ids: Iterable[UUID],
    start_at: datetime | None,
    end_at: datetime | None,
    evidence: dict[str, Any],
    config: BaseModel,
    deduplication_context: tuple[str, ...] = (),
) -> DetectionFinding:
    return create_finding(
        detector_name=detector_name,
        detector_version=detector_version,
        category=category,
        severity=severity,
        title=title,
        explanation=explanation,
        dataset_id=dataset_id,
        account_ids=tuple(account_ids),
        transaction_ids=tuple(transaction_ids),
        start_at=start_at,
        end_at=end_at,
        evidence=evidence,
        parameters=parameters_json(config),
        deduplication_context=deduplication_context,
    )


def latest_inclusive_window(
    graph: TransactionGraph, seconds: int
) -> tuple[datetime, datetime] | None:
    """Return the latest graph-time half-open window containing its latest edge."""

    edges = sorted_edges(graph)
    if not edges:
        return None
    end = max(edge_time(edge[3]) for edge in edges) + timedelta(microseconds=1)
    return end - timedelta(seconds=seconds), end
