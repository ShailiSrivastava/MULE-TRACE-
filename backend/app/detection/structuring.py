"""Configured, per-currency repeated amount-band transaction indicators."""

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
    create_detector_finding,
    edge_id,
    edge_time,
    sorted_edges,
)
from app.detection.config import StructuringConfig
from app.graph.builder import TransactionGraph

Edge = tuple[UUID, UUID, UUID, dict]


def _seconds_between(start, end) -> str:
    delta = end - start
    seconds = Decimal(delta.days * 86_400 + delta.seconds)
    seconds += Decimal(delta.microseconds) / Decimal(1_000_000)
    return format(seconds, "f")


class StructuringDetector:
    name = "structuring"
    config_key = "structuring"
    version = DETECTOR_VERSION

    def detect(
        self,
        graph: TransactionGraph,
        *,
        dataset_id: UUID | None,
        config: BaseModel,
    ) -> DetectorOutput:
        settings = cast(StructuringConfig, config)
        if not settings.threshold_bands_by_currency:
            return DetectorOutput(
                (),
                {
                    "windows_examined": 0,
                    "configured_currency_count": 0,
                    "truncated": False,
                },
            )

        groups: dict[tuple[UUID, str, int], list[Edge]] = {}
        for source, target, key, attributes in sorted_edges(graph):
            currency = str(attributes["currency"]).upper()
            for index, band in enumerate(
                settings.threshold_bands_by_currency.get(currency, ())
            ):
                if band.minimum_amount <= attributes["amount"] <= band.maximum_amount:
                    groups.setdefault((source, currency, index), []).append(
                        (source, target, edge_id(key, attributes), attributes)
                    )

        findings = []
        windows_examined = 0
        truncated = False
        stop = False
        for (sender_id, currency, band_index), edges in sorted(
            groups.items(), key=lambda item: (str(item[0][0]), item[0][1], item[0][2])
        ):
            band = settings.threshold_bands_by_currency[currency][band_index]
            left = 0
            right = 0
            active_days: Counter = Counter()
            total_amount = Decimal(0)
            while left < len(edges):
                if windows_examined >= settings.max_windows_examined:
                    truncated = True
                    stop = True
                    break
                start_at = edge_time(edges[left][3])
                boundary = start_at + timedelta(seconds=settings.window_seconds)
                while right < len(edges) and edge_time(edges[right][3]) < boundary:
                    attributes = edges[right][3]
                    active_days[edge_time(attributes).date()] += 1
                    total_amount += attributes["amount"]
                    right += 1
                windows_examined += 1
                count = right - left
                if (
                    count >= settings.minimum_transaction_count
                    and len(active_days) >= settings.minimum_active_days
                ):
                    if len(findings) >= settings.max_findings:
                        truncated = True
                        stop = True
                        break
                    window_edges = edges[left:right]
                    transaction_ids = tuple(edge[2] for edge in window_edges)
                    times = [edge_time(edge[3]) for edge in window_edges]
                    intervals = [
                        _seconds_between(times[index - 1], times[index])
                        for index in range(1, len(times))
                    ]
                    findings.append(
                        create_detector_finding(
                            detector_name=self.name,
                            detector_version=self.version,
                            category="repeated_amount_band_activity",
                            severity="medium",
                            title="Repeated transactions in a configured amount band",
                            explanation=(
                                f"{count} outgoing {currency} transactions from one account fell "
                                f"within a configured amount band over {len(active_days)} active day(s)."
                            ),
                            dataset_id=dataset_id,
                            account_ids=(
                                sender_id,
                                *sorted({edge[1] for edge in window_edges}, key=str),
                            ),
                            transaction_ids=transaction_ids,
                            start_at=times[0],
                            end_at=times[-1],
                            evidence={
                                "sender_account_id": str(sender_id),
                                "currency": currency,
                                "configured_band": {
                                    "minimum_amount_inclusive": format(
                                        band.minimum_amount, "f"
                                    ),
                                    "maximum_amount_inclusive": format(
                                        band.maximum_amount, "f"
                                    ),
                                },
                                "transaction_count": count,
                                "active_utc_days": sorted(
                                    day.isoformat() for day in active_days
                                ),
                                "total_amount_same_currency": format(total_amount, "f"),
                                "intervals_seconds": intervals,
                                "window_seconds": settings.window_seconds,
                                "window_boundary": "start-inclusive/end-exclusive",
                            },
                            config=settings,
                            deduplication_context=(
                                currency,
                                str(band.minimum_amount),
                                str(band.maximum_amount),
                                *map(str, transaction_ids),
                            ),
                        )
                    )

                if left < right:
                    attributes = edges[left][3]
                    day = edge_time(attributes).date()
                    active_days[day] -= 1
                    if active_days[day] == 0:
                        del active_days[day]
                    total_amount -= attributes["amount"]
                left += 1
            if stop:
                break

        findings.sort(key=lambda item: item.deduplication_key)
        return DetectorOutput(
            findings=tuple(findings),
            statistics={
                "windows_examined": windows_examined,
                "configured_currency_count": len(settings.threshold_bands_by_currency),
                "truncated": truncated,
            },
        )
