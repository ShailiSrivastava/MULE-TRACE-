"""Bounded directed cycle enumeration with transaction-level edge choices."""

from __future__ import annotations

from datetime import timedelta
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
from app.detection.config import CircularMovementConfig
from app.graph.builder import TransactionGraph

EdgeOption = tuple[UUID, dict]


class CircularMovementDetector:
    name = "circular_movement"
    config_key = "circular_movement"
    version = DETECTOR_VERSION

    def detect(
        self,
        graph: TransactionGraph,
        *,
        dataset_id: UUID | None,
        config: BaseModel,
    ) -> DetectorOutput:
        settings = cast(CircularMovementConfig, config)
        if graph.number_of_edges() == 0:
            return DetectorOutput(
                (), {"cycles_examined": 0, "edge_expansions": 0, "truncated": False}
            )

        edge_options: dict[tuple[UUID, UUID], list[EdgeOption]] = {}
        for source, target, key, attributes in sorted_edges(graph):
            edge_options.setdefault((source, target), []).append(
                (edge_id(key, attributes), attributes)
            )
        adjacency = {
            node: tuple(sorted(graph.successors(node), key=str)) for node in graph.nodes
        }

        findings = []
        seen: set[tuple[str, ...]] = set()
        cycles_examined = 0
        edge_expansions = 0
        truncated = False
        stop = False
        max_elapsed = timedelta(seconds=settings.time_window_seconds)

        def emit_edge_combinations(
            nodes: tuple[UUID, ...], pairs: tuple[tuple[UUID, UUID], ...]
        ) -> None:
            nonlocal cycles_examined, edge_expansions, truncated, stop
            chosen: list[EdgeOption] = []
            times: list = []

            def choose(index: int) -> None:
                nonlocal cycles_examined, edge_expansions, truncated, stop
                if stop:
                    return
                if index == len(pairs):
                    if max(times) - min(times) >= max_elapsed:
                        return
                    ordered_ids = tuple(option[0] for option in chosen)
                    canonical = min(
                        tuple(
                            str(item)
                            for item in ordered_ids[offset:] + ordered_ids[:offset]
                        )
                        for offset in range(len(ordered_ids))
                    )
                    if canonical in seen:
                        return
                    seen.add(canonical)
                    if cycles_examined >= settings.maximum_cycles:
                        truncated = True
                        stop = True
                        return
                    cycles_examined += 1
                    start = min(times)
                    end = max(times)
                    closed_path = (*nodes, nodes[0])
                    transaction_sequence = [
                        {
                            "transaction_id": str(option[0]),
                            "source": str(pairs[position][0]),
                            "target": str(pairs[position][1]),
                            "amount": format(option[1]["amount"], "f"),
                            "currency": str(option[1]["currency"]).upper(),
                            "occurred_at": edge_time(option[1])
                            .isoformat()
                            .replace("+00:00", "Z"),
                        }
                        for position, option in enumerate(chosen)
                    ]
                    findings.append(
                        create_detector_finding(
                            detector_name=self.name,
                            detector_version=self.version,
                            category="directed_cycle",
                            severity="high",
                            title="Directed transaction cycle",
                            explanation=(
                                f"A directed cycle of {len(nodes)} accounts has transaction "
                                f"evidence spanning less than {settings.time_window_seconds} seconds."
                            ),
                            dataset_id=dataset_id,
                            account_ids=nodes,
                            transaction_ids=ordered_ids,
                            start_at=start,
                            end_at=end,
                            evidence={
                                "closed_account_path": [
                                    str(item) for item in closed_path
                                ],
                                "transaction_sequence": transaction_sequence,
                                "cycle_length": len(nodes),
                                "time_window_seconds": settings.time_window_seconds,
                                "cycle_boundary": "elapsed time must be less than configured window",
                            },
                            config=settings,
                            deduplication_context=canonical,
                        )
                    )
                    return

                for transaction_id, attributes in edge_options[pairs[index]]:
                    if edge_expansions >= settings.maximum_edge_expansions:
                        truncated = True
                        stop = True
                        return
                    edge_expansions += 1
                    occurred_at = edge_time(attributes)
                    candidate_times = (*times, occurred_at)
                    if (
                        candidate_times
                        and max(candidate_times) - min(candidate_times) >= max_elapsed
                    ):
                        continue
                    chosen.append((transaction_id, attributes))
                    times.append(occurred_at)
                    choose(index + 1)
                    chosen.pop()
                    times.pop()
                    if stop:
                        return

            choose(0)

        def visit(start: UUID, current: UUID, nodes: tuple[UUID, ...]) -> None:
            nonlocal edge_expansions, truncated, stop
            if stop:
                return
            for neighbor in adjacency.get(current, ()):
                if edge_expansions >= settings.maximum_edge_expansions:
                    truncated = True
                    stop = True
                    return
                edge_expansions += 1
                if neighbor == start:
                    cycle_length = len(nodes)
                    if (
                        settings.minimum_cycle_length
                        <= cycle_length
                        <= settings.maximum_cycle_length
                    ):
                        cycle_nodes = (*nodes, start)
                        pairs = tuple(
                            (cycle_nodes[index], cycle_nodes[index + 1])
                            for index in range(cycle_length)
                        )
                        emit_edge_combinations(nodes, pairs)
                elif (
                    neighbor not in nodes
                    and str(neighbor) > str(start)
                    and len(nodes) < settings.maximum_cycle_length
                ):
                    visit(start, neighbor, (*nodes, neighbor))
                if stop:
                    return

        for start in sorted(graph.nodes, key=str):
            visit(start, start, (start,))
            if stop:
                break

        findings.sort(key=lambda item: item.deduplication_key)
        return DetectorOutput(
            findings=tuple(findings),
            statistics={
                "cycles_examined": cycles_examined,
                "edge_expansions": edge_expansions,
                "truncated": truncated,
            },
        )
