"""Median/MAD and within-account frequency deviation indicators."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
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
from app.detection.config import UnusualActivityConfig
from app.graph.builder import TransactionGraph

EdgeEvent = tuple[UUID, UUID, Decimal, str, datetime, str]


def _seconds_decimal(value: timedelta) -> Decimal:
    return Decimal(value.days * 86_400 + value.seconds) + Decimal(
        value.microseconds
    ) / Decimal(1_000_000)


class UnusualActivityDetector:
    name = "unusual_activity"
    config_key = "unusual_activity"
    version = DETECTOR_VERSION

    def detect(
        self,
        graph: TransactionGraph,
        *,
        dataset_id: UUID | None,
        config: BaseModel,
    ) -> DetectorOutput:
        settings = cast(UnusualActivityConfig, config)
        edges = sorted_edges(graph)
        if not edges:
            return DetectorOutput(
                (),
                {
                    "observed_accounts": 0,
                    "insufficient_history_accounts": 0,
                    "insufficient_history_currencies": 0,
                    "truncated": False,
                },
            )

        by_account: dict[UUID, list[EdgeEvent]] = {node: [] for node in graph.nodes}
        for source, target, key, attributes in edges:
            transaction_id = edge_id(key, attributes)
            occurred_at = edge_time(attributes)
            amount = attributes["amount"]
            currency = str(attributes["currency"]).upper()
            by_account.setdefault(source, []).append(
                (transaction_id, source, amount, currency, occurred_at, "outgoing")
            )
            if target != source:
                by_account.setdefault(target, []).append(
                    (transaction_id, target, amount, currency, occurred_at, "incoming")
                )

        latest = max(edge_time(edge[3]) for edge in edges)
        observation_end = latest + timedelta(microseconds=1)
        duration = timedelta(seconds=settings.activity_window_seconds)
        observation_start = observation_end - duration
        earliest = min(edge_time(edge[3]) for edge in edges)
        available_periods = min(
            settings.baseline_periods,
            max(
                0,
                (observation_start - earliest)
                // timedelta(seconds=settings.activity_window_seconds),
            ),
        )
        baseline_start = observation_start - duration * available_periods
        findings = []
        insufficient_accounts: set[UUID] = set()
        insufficient_currencies = 0
        frequency_findings = 0
        amount_findings = 0
        truncated = False

        for account_id in sorted(by_account, key=str):
            events = sorted(
                by_account[account_id], key=lambda item: (item[4], str(item[0]))
            )
            observed = [
                event
                for event in events
                if observation_start <= event[4] < observation_end
            ]
            baseline = [
                event
                for event in events
                if baseline_start <= event[4] < observation_start
            ]
            if not observed:
                continue

            if (
                available_periods < settings.minimum_baseline_periods
                or len(baseline) < settings.minimum_baseline_transactions
            ):
                insufficient_accounts.add(account_id)
            else:
                counts = [0] * available_periods
                for event in baseline:
                    period_index = (event[4] - baseline_start) // duration
                    if 0 <= period_index < available_periods:
                        counts[period_index] += 1
                mean = Decimal(sum(counts)) / Decimal(len(counts))
                variance = sum(
                    (Decimal(count) - mean) ** 2 for count in counts
                ) / Decimal(len(counts))
                deviation = variance.sqrt()
                expected_max = (
                    mean + settings.frequency_standard_deviation_multiplier * deviation
                )
                if (
                    len(observed) >= settings.minimum_observed_transactions
                    and Decimal(len(observed)) > expected_max
                ):
                    tx_ids = tuple(event[0] for event in observed)
                    incoming_count = sum(
                        1 for event in observed if event[5] == "incoming"
                    )
                    outgoing_count = len(observed) - incoming_count
                    finding = create_detector_finding(
                        detector_name=self.name,
                        detector_version=self.version,
                        category="unusual_transaction_frequency",
                        severity="medium",
                        title="Transaction frequency differs from account history",
                        explanation=(
                            f"The account had {len(observed)} transactions in the observation "
                            f"window, above its historical mean of {mean:f} plus "
                            f"{settings.frequency_standard_deviation_multiplier:f} standard deviations."
                        ),
                        dataset_id=dataset_id,
                        account_ids=(account_id,),
                        transaction_ids=tx_ids,
                        start_at=min(event[4] for event in observed),
                        end_at=max(event[4] for event in observed),
                        evidence={
                            "account_id": str(account_id),
                            "feature": "incident_transaction_count",
                            "observation_count": len(observed),
                            "incoming_count": incoming_count,
                            "outgoing_count": outgoing_count,
                            "baseline_period_counts": counts,
                            "baseline_periods_used": available_periods,
                            "baseline_mean": format(mean, "f"),
                            "baseline_standard_deviation": format(deviation, "f"),
                            "comparison_threshold": format(expected_max, "f"),
                            "observation_window": {
                                "start_at": observation_start.isoformat().replace(
                                    "+00:00", "Z"
                                ),
                                "end_at": observation_end.isoformat().replace(
                                    "+00:00", "Z"
                                ),
                                "boundary": "start-inclusive/end-exclusive",
                            },
                        },
                        config=settings,
                        deduplication_context=("frequency", *map(str, tx_ids)),
                    )
                    findings.append(finding)
                    frequency_findings += 1

            baseline_by_currency: dict[str, list[Decimal]] = {}
            observed_by_currency: dict[str, list[EdgeEvent]] = {}
            for event in baseline:
                baseline_by_currency.setdefault(event[3], []).append(event[2])
            for event in observed:
                observed_by_currency.setdefault(event[3], []).append(event)

            for currency in sorted(observed_by_currency):
                historical = baseline_by_currency.get(currency, [])
                if len(historical) < settings.minimum_amount_baseline_transactions:
                    insufficient_currencies += 1
                    continue
                center = median(historical)
                mad = median([abs(value - center) for value in historical])
                threshold = center + settings.amount_mad_multiplier * mad
                outliers = [
                    event
                    for event in observed_by_currency[currency]
                    if event[2] > threshold
                ]
                if not outliers:
                    continue
                tx_ids = tuple(event[0] for event in outliers)
                finding = create_detector_finding(
                    detector_name=self.name,
                    detector_version=self.version,
                    category="unusual_transaction_amount",
                    severity="medium",
                    title="Transaction amount differs from same-currency history",
                    explanation=(
                        f"{len(outliers)} {currency} transaction amount(s) exceeded the "
                        "account's historical median plus the configured MAD multiple."
                    ),
                    dataset_id=dataset_id,
                    account_ids=(account_id,),
                    transaction_ids=tx_ids,
                    start_at=min(event[4] for event in outliers),
                    end_at=max(event[4] for event in outliers),
                    evidence={
                        "account_id": str(account_id),
                        "feature": "amount_by_currency",
                        "currency": currency,
                        "historical_transaction_count": len(historical),
                        "historical_median": format(center, "f"),
                        "historical_median_absolute_deviation": format(mad, "f"),
                        "comparison_threshold": format(threshold, "f"),
                        "outlier_transactions": [
                            {
                                "transaction_id": str(event[0]),
                                "amount": format(event[2], "f"),
                                "occurred_at": event[4]
                                .isoformat()
                                .replace("+00:00", "Z"),
                            }
                            for event in outliers
                        ],
                    },
                    config=settings,
                    deduplication_context=(currency, *map(str, tx_ids)),
                )
                findings.append(finding)
                amount_findings += 1

            if len(findings) >= settings.max_findings:
                truncated = True
                findings = findings[: settings.max_findings]
                break

        findings.sort(key=lambda item: item.deduplication_key)
        return DetectorOutput(
            findings=tuple(findings),
            statistics={
                "observed_accounts": sum(
                    any(
                        observation_start <= event[4] < observation_end
                        for event in value
                    )
                    for value in by_account.values()
                ),
                "frequency_findings": frequency_findings,
                "amount_findings": amount_findings,
                "insufficient_history_accounts": len(insufficient_accounts),
                "insufficient_history_currencies": insufficient_currencies,
                "truncated": truncated,
            },
        )
