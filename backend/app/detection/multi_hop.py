"""Multi-hop movement indicators reusing the Phase 7 bounded path finder."""

from __future__ import annotations

from datetime import timedelta
from itertools import pairwise
from typing import cast
from uuid import UUID

import networkx as nx
from pydantic import BaseModel

from app.detection.base import (
    DETECTOR_VERSION,
    DetectorOutput,
    create_detector_finding,
    latest_inclusive_window,
)
from app.detection.config import MultiHopConfig
from app.graph.builder import TransactionGraph
from app.graph.models import GraphLimitExceeded
from app.graph.paths import find_bounded_paths


class MultiHopDetector:
    name = "multi_hop"
    config_key = "multi_hop"
    version = DETECTOR_VERSION

    def detect(
        self,
        graph: TransactionGraph,
        *,
        dataset_id: UUID | None,
        config: BaseModel,
    ) -> DetectorOutput:
        settings = cast(MultiHopConfig, config)
        window = latest_inclusive_window(graph, settings.time_window_seconds)
        if window is None:
            return DetectorOutput(
                (), {"pairs_examined": 0, "paths_found": 0, "truncated": False}
            )
        start_at, end_at = window

        def edge_allowed(source, target, key) -> bool:
            attributes = graph.edges[source, target, key]
            occurred_at = attributes["occurred_at"]
            if not (start_at <= occurred_at < end_at):
                return False
            currency = str(attributes["currency"]).upper()
            minimum = settings.minimum_amount_by_currency.get(currency)
            return minimum is None or attributes["amount"] >= minimum

        time_filtered = nx.subgraph_view(graph, filter_edge=edge_allowed)
        sources = sorted(
            (node for node in time_filtered if time_filtered.out_degree(node) > 0),
            key=str,
        )
        targets = sorted(
            (node for node in time_filtered if time_filtered.in_degree(node) > 0),
            key=str,
        )
        findings = []
        pairs_examined = 0
        total_expansions = 0
        truncated = False
        result_limit = min(settings.maximum_paths, settings.max_findings)

        for source in sources:
            for target in targets:
                if source == target:
                    continue
                if pairs_examined >= settings.maximum_pairs_examined:
                    truncated = True
                    break
                remaining_expansions = (
                    settings.maximum_total_expansions - total_expansions
                )
                if remaining_expansions <= 0:
                    truncated = True
                    break
                pairs_examined += 1
                # Exclude a direct edge for this pair so every result includes
                # at least one intermediary account.
                pair_graph = nx.subgraph_view(
                    time_filtered,
                    filter_edge=lambda u, v, k, s=source, t=target: (
                        not (u == s and v == t)
                    ),
                )
                try:
                    result = find_bounded_paths(
                        pair_graph,
                        source,
                        target,
                        max_hops=settings.maximum_hops,
                        max_paths=max(1, result_limit - len(findings)),
                        max_expansions=min(
                            settings.maximum_expansions_per_pair,
                            remaining_expansions,
                        ),
                    )
                except GraphLimitExceeded:
                    truncated = True
                    break
                total_expansions += result.expanded_edges
                if result.truncated:
                    truncated = True
                for path in result.paths:
                    path_times = tuple(
                        transaction.occurred_at for transaction in path.transactions
                    )
                    if any(
                        current < previous for previous, current in pairwise(path_times)
                    ):
                        continue
                    if path_times[-1] - path_times[0] >= timedelta(
                        seconds=settings.time_window_seconds
                    ):
                        continue
                    if len(findings) >= result_limit:
                        truncated = True
                        break
                    transaction_ids = tuple(
                        transaction.transaction_id for transaction in path.transactions
                    )
                    transfers = [
                        {
                            "transaction_id": str(transaction.transaction_id),
                            "source": str(transaction.source),
                            "target": str(transaction.target),
                            "amount": format(transaction.amount, "f"),
                            "currency": transaction.currency,
                            "occurred_at": transaction.occurred_at.isoformat().replace(
                                "+00:00", "Z"
                            ),
                        }
                        for transaction in path.transactions
                    ]
                    findings.append(
                        create_detector_finding(
                            detector_name=self.name,
                            detector_version=self.version,
                            category="multi_hop_movement",
                            severity="medium",
                            title="Multi-hop transaction movement",
                            explanation=(
                                f"A directed path passed through {len(path.accounts) - 2} "
                                "intermediary accounts within the configured time window."
                            ),
                            dataset_id=dataset_id,
                            account_ids=path.accounts,
                            transaction_ids=transaction_ids,
                            start_at=min(
                                item.occurred_at for item in path.transactions
                            ),
                            end_at=max(item.occurred_at for item in path.transactions),
                            evidence={
                                "account_path": [str(item) for item in path.accounts],
                                "transaction_sequence": transfers,
                                "hop_count": len(path.transactions),
                                "intermediary_account_count": len(path.accounts) - 2,
                                "minimum_amount_by_currency": {
                                    code: format(amount, "f")
                                    for code, amount in settings.minimum_amount_by_currency.items()
                                },
                                "time_window": {
                                    "start_at": start_at.isoformat().replace(
                                        "+00:00", "Z"
                                    ),
                                    "end_at": end_at.isoformat().replace("+00:00", "Z"),
                                    "boundary": "start-inclusive/end-exclusive",
                                },
                            },
                            config=settings,
                            deduplication_context=tuple(map(str, transaction_ids)),
                        )
                    )
                if len(findings) >= result_limit:
                    truncated = True
                    break
            if truncated and (
                pairs_examined >= settings.maximum_pairs_examined
                or total_expansions >= settings.maximum_total_expansions
                or len(findings) >= result_limit
            ):
                break

        findings.sort(key=lambda item: item.deduplication_key)
        return DetectorOutput(
            findings=tuple(findings),
            statistics={
                "pairs_examined": pairs_examined,
                "paths_found": len(findings),
                "edge_expansions": total_expansions,
                "truncated": truncated,
            },
        )
