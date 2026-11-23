"""Detection of continuous, time-ordered rapid transfer chains."""

from __future__ import annotations

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
from app.detection.config import RapidTransfersConfig
from app.graph.builder import TransactionGraph


class RapidTransferDetector:
    name = "rapid_transfers"
    config_key = "rapid_transfers"
    version = DETECTOR_VERSION

    def detect(
        self,
        graph: TransactionGraph,
        *,
        dataset_id: UUID | None,
        config: BaseModel,
    ) -> DetectorOutput:
        settings = cast(RapidTransfersConfig, config)
        if graph.number_of_edges() == 0:
            return DetectorOutput(
                (), {"edges_considered": 0, "edge_expansions": 0, "truncated": False}
            )

        adjacency: dict[UUID, list[tuple[UUID, UUID, UUID, dict]]] = {}
        eligible_edges = 0
        for source, target, key, attributes in sorted_edges(graph):
            currency = str(attributes["currency"]).upper()
            threshold = settings.minimum_amount_by_currency.get(currency)
            if threshold is not None and attributes["amount"] < threshold:
                continue
            adjacency.setdefault(source, []).append(
                (source, target, edge_id(key, attributes), attributes)
            )
            eligible_edges += 1

        findings = []
        edge_expansions = 0
        truncated = False
        stop = False
        maximum_elapsed = timedelta(seconds=settings.maximum_elapsed_seconds)

        def visit(
            path: tuple[tuple[UUID, UUID, UUID, dict], ...],
            accounts: tuple[UUID, ...],
        ) -> None:
            nonlocal edge_expansions, truncated, stop
            if stop:
                return
            first_time = edge_time(path[0][3])
            last_time = edge_time(path[-1][3])
            if (
                len(path) >= settings.minimum_transaction_count
                and len(set(accounts)) >= settings.minimum_distinct_accounts
            ):
                if len(findings) >= settings.max_findings:
                    truncated = True
                    stop = True
                    return
                transaction_ids = tuple(item[2] for item in path)
                amount_totals: dict[str, Decimal] = {}
                for _, _, _, attributes in path:
                    currency = str(attributes["currency"]).upper()
                    amount_totals[currency] = (
                        amount_totals.get(currency, Decimal(0)) + attributes["amount"]
                    )
                totals = {
                    key: format(value, "f")
                    for key, value in sorted(amount_totals.items())
                }
                transfers = [
                    {
                        "transaction_id": str(transaction_id),
                        "source": str(source),
                        "target": str(target),
                        "amount": format(attributes["amount"], "f"),
                        "currency": str(attributes["currency"]).upper(),
                        "occurred_at": edge_time(attributes)
                        .isoformat()
                        .replace("+00:00", "Z"),
                    }
                    for source, target, transaction_id, attributes in path
                ]
                finding = create_detector_finding(
                    detector_name=self.name,
                    detector_version=self.version,
                    category="rapid_transfer_chain",
                    severity="high",
                    title="Rapid successive transfer chain",
                    explanation=(
                        f"A continuous directed chain of {len(path)} transfers across "
                        f"{len(set(accounts))} accounts occurred within "
                        f"{(last_time - first_time).total_seconds():g} seconds."
                    ),
                    dataset_id=dataset_id,
                    account_ids=accounts,
                    transaction_ids=transaction_ids,
                    start_at=first_time,
                    end_at=last_time,
                    evidence={
                        "account_path": [str(account_id) for account_id in accounts],
                        "transfer_sequence": transfers,
                        "transaction_count": len(path),
                        "distinct_account_count": len(set(accounts)),
                        "elapsed_seconds": (last_time - first_time).total_seconds(),
                        "amount_totals_by_currency": totals,
                    },
                    config=settings,
                    deduplication_context=tuple(map(str, transaction_ids)),
                )
                findings.append(finding)

            if len(path) >= settings.maximum_path_length:
                return
            current = path[-1][1]
            previous_time = edge_time(path[-1][3])
            for edge in adjacency.get(current, []):
                if edge_expansions >= settings.max_edge_expansions:
                    truncated = True
                    stop = True
                    return
                edge_expansions += 1
                next_time = edge_time(edge[3])
                if (
                    next_time < previous_time
                    or next_time - first_time >= maximum_elapsed
                ):
                    continue
                if edge[1] in accounts:
                    continue
                visit((*path, edge), (*accounts, edge[1]))
                if stop:
                    return

        for edge in sorted_edges(graph):
            if edge_expansions >= settings.max_edge_expansions:
                truncated = True
                break
            source, target, key, attributes = edge
            currency = str(attributes["currency"]).upper()
            threshold = settings.minimum_amount_by_currency.get(currency)
            if threshold is not None and attributes["amount"] < threshold:
                continue
            edge_expansions += 1
            visit(
                ((source, target, edge_id(key, attributes), attributes),),
                (source, target),
            )
            if stop:
                break

        return DetectorOutput(
            findings=tuple(findings),
            statistics={
                "edges_considered": eligible_edges,
                "edge_expansions": edge_expansions,
                "truncated": truncated,
            },
        )
