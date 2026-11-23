"""Network-level components, density, subgraphs, and neighborhoods."""

from __future__ import annotations

from collections import deque
from typing import Literal
from uuid import UUID

import networkx as nx

from app.graph.builder import TransactionGraph
from app.graph.models import (
    DEFAULT_GRAPH_LIMITS,
    ComponentSummary,
    GraphLimitExceeded,
    GraphLimits,
    NetworkMetrics,
)

NeighborhoodDirection = Literal["incoming", "outgoing", "both"]


def _component_summaries(components) -> tuple[ComponentSummary, ...]:
    summaries = [
        ComponentSummary(tuple(sorted(component, key=str))) for component in components
    ]
    return tuple(
        sorted(summaries, key=lambda item: (-item.size, tuple(map(str, item.accounts))))
    )


def connected_components(
    graph: TransactionGraph,
) -> dict[str, tuple[ComponentSummary, ...]]:
    """Return weak and strong components, ordered by size then UUID membership."""

    return {
        "weak": _component_summaries(nx.weakly_connected_components(graph)),
        "strong": _component_summaries(nx.strongly_connected_components(graph)),
    }


def network_metrics(graph: TransactionGraph) -> NetworkMetrics:
    """Return counts and directed simple-topology density.

    Density is the fraction of possible directed, non-self account pairs that
    have at least one transaction. Parallel transactions do not increase it;
    self-loops are excluded. For fewer than two accounts density is zero.
    """

    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    if node_count < 2:
        density = 0.0
    else:
        arcs = {
            (source, target) for source, target in graph.edges() if source != target
        }
        density = len(arcs) / (node_count * (node_count - 1))
    return NetworkMetrics(
        node_count=node_count,
        edge_count=edge_count,
        directed_density=density,
    )


def extract_subgraph(
    graph: TransactionGraph, account_ids: set[UUID] | frozenset[UUID]
) -> TransactionGraph:
    """Return a copied induced subgraph for the selected accounts."""

    return graph.subgraph(set(account_ids) & set(graph.nodes)).copy()


def extract_neighborhood(
    graph: TransactionGraph,
    account_id: UUID,
    *,
    depth: int,
    direction: NeighborhoodDirection = "both",
    limits: GraphLimits = DEFAULT_GRAPH_LIMITS,
) -> TransactionGraph:
    """Return nodes at most ``depth`` hops from a root in the chosen direction.

    ``both`` follows incoming and outgoing links, while ``incoming`` and
    ``outgoing`` preserve the corresponding money-flow direction. Depth zero
    returns the root alone. A missing root returns an empty graph with metadata.
    """

    if depth < 0 or depth > limits.max_neighborhood_depth:
        raise GraphLimitExceeded(
            f"Neighborhood depth must be between 0 and {limits.max_neighborhood_depth}."
        )
    if direction not in {"incoming", "outgoing", "both"}:
        raise ValueError("direction must be incoming, outgoing, or both.")
    if account_id not in graph:
        empty = graph.__class__()
        empty.graph.update(graph.graph)
        return empty

    distances = {account_id: 0}
    queue = deque([account_id])
    while queue:
        current = queue.popleft()
        current_depth = distances[current]
        if current_depth >= depth:
            continue
        neighbors: set[UUID] = set()
        if direction in {"incoming", "both"}:
            neighbors.update(graph.predecessors(current))
        if direction in {"outgoing", "both"}:
            neighbors.update(graph.successors(current))
        for neighbor in sorted(neighbors, key=str):
            if neighbor not in distances:
                distances[neighbor] = current_depth + 1
                queue.append(neighbor)
    return extract_subgraph(graph, set(distances))
