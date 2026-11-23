"""Rolling-window fan-in and fan-out detectors with unique-party counts."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import BaseModel

from app.detection.base import (
    DETECTOR_VERSION,
    DetectorOutput,
    amount_string,
    create_detector_finding,
    edge_id,
    edge_time,
    sorted_edges,
)
from app.detection.config import FanInConfig, FanOutConfig
from app.graph.builder import TransactionGraph

Edge = tuple[UUID, UUID, UUID, dict]


def _detect_fan(
    graph: TransactionGraph,
    *,
    dataset_id: UUID | None,
    settings: FanInConfig | FanOutConfig,
    incoming: bool,
    detector_name: str,
) -> DetectorOutput:
    if graph.number_of_edges() == 0:
        return DetectorOutput((), {"windows_examined": 0, "truncated": False})

    by_center: dict[UUID, list[Edge]] = {}
    for source, target, key, attributes in sorted_edges(graph):
        center = target if incoming else source
        by_center.setdefault(center, []).append(
            (source, target, edge_id(key, attributes), attributes)
        )

    minimum_unique = (
        settings.minimum_unique_senders
        if incoming
        else cast(FanOutConfig, settings).minimum_unique_receivers
    )
    minimum_transactions = (
        settings.minimum_incoming_transactions
        if incoming
        else cast(FanOutConfig, settings).minimum_outgoing_transactions
    )
    minimum_amounts = settings.minimum_total_amount_by_currency
    findings = []
    windows_examined = 0
    truncated = False
    stop = False

    for center in sorted(by_center, key=str):
        edges = by_center[center]
        counterparties: Counter[UUID] = Counter()
        totals: dict[str, Decimal] = {}
        left = 0
        right = 0
        while left < len(edges):
            if windows_examined >= settings.max_windows_examined:
                truncated = True
                stop = True
                break
            start_at = edge_time(edges[left][3])
            boundary = start_at + timedelta(seconds=settings.window_seconds)
            while right < len(edges) and edge_time(edges[right][3]) < boundary:
                source, target, _, attributes = edges[right]
                counterparty = source if incoming else target
                counterparties[counterparty] += 1
                currency = str(attributes["currency"]).upper()
                totals[currency] = (
                    totals.get(currency, Decimal(0)) + attributes["amount"]
                )
                right += 1
            windows_examined += 1
            window_count = right - left
            amount_qualifies = not minimum_amounts or any(
                totals.get(currency, Decimal(0)) >= threshold
                for currency, threshold in minimum_amounts.items()
            )
            unique_count = len(counterparties)
            if (
                window_count >= minimum_transactions
                and unique_count >= minimum_unique
                and amount_qualifies
            ):
                if len(findings) >= settings.max_findings:
                    truncated = True
                    stop = True
                    break
                window_edges = edges[left:right]
                transaction_ids = tuple(edge[2] for edge in window_edges)
                involved = (center, *sorted(counterparties, key=str))
                start = edge_time(window_edges[0][3])
                end = edge_time(window_edges[-1][3])
                total_values = {
                    currency: amount_string(value)
                    for currency, value in sorted(totals.items())
                }
                direction = "incoming" if incoming else "outgoing"
                finding = create_detector_finding(
                    detector_name=detector_name,
                    detector_version=DETECTOR_VERSION,
                    category="fan_in" if incoming else "fan_out",
                    severity="medium",
                    title="Many distinct accounts send into one account"
                    if incoming
                    else "One account sends to many distinct accounts",
                    explanation=(
                        f"{window_count} {direction} transactions involved "
                        f"{unique_count} distinct counterparties within a "
                        f"{settings.window_seconds}-second rolling window."
                    ),
                    dataset_id=dataset_id,
                    account_ids=involved,
                    transaction_ids=transaction_ids,
                    start_at=start,
                    end_at=end,
                    evidence={
                        "center_account_id": str(center),
                        "direction": direction,
                        "transaction_count": window_count,
                        "unique_counterparty_count": unique_count,
                        "counterparty_ids": [
                            str(item) for item in sorted(counterparties, key=str)
                        ],
                        "amount_totals_by_currency": total_values,
                        "window_seconds": settings.window_seconds,
                        "window_boundary": "start-inclusive/end-exclusive",
                    },
                    config=settings,
                    deduplication_context=(direction, *map(str, transaction_ids)),
                )
                findings.append(finding)

            if left < right:
                source, target, _, attributes = edges[left]
                counterparty = source if incoming else target
                counterparties[counterparty] -= 1
                if counterparties[counterparty] == 0:
                    del counterparties[counterparty]
                currency = str(attributes["currency"]).upper()
                totals[currency] -= attributes["amount"]
                if totals[currency] == 0:
                    del totals[currency]
            left += 1
        if stop:
            break

    return DetectorOutput(
        findings=tuple(findings),
        statistics={"windows_examined": windows_examined, "truncated": truncated},
    )


class FanInDetector:
    name = "fan_in"
    config_key = "fan_in"
    version = DETECTOR_VERSION

    def detect(self, graph, *, dataset_id, config: BaseModel) -> DetectorOutput:
        return _detect_fan(
            graph,
            dataset_id=dataset_id,
            settings=cast(FanInConfig, config),
            incoming=True,
            detector_name=self.name,
        )


class FanOutDetector:
    name = "fan_out"
    config_key = "fan_out"
    version = DETECTOR_VERSION

    def detect(self, graph, *, dataset_id, config: BaseModel) -> DetectorOutput:
        return _detect_fan(
            graph,
            dataset_id=dataset_id,
            settings=cast(FanOutConfig, config),
            incoming=False,
            detector_name=self.name,
        )
