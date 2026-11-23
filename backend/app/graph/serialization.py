"""Stable, JSON-safe graph serialization with explicit sensitive-field allowlists."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.graph.builder import TransactionGraph
from app.graph.models import normalize_utc


def _uuid_string(value: UUID | str) -> str:
    return str(value)


def _utc_isoformat(value: datetime) -> str:
    return (
        normalize_utc(value, field_name="occurred_at")
        .isoformat()
        .replace("+00:00", "Z")
    )


def _amount_string(value: Decimal) -> str:
    return format(value, "f")


def serialize_graph(graph: TransactionGraph) -> dict[str, Any]:
    """Serialize a graph independent of NetworkX's adjacency representation.

    Account metadata and external IDs are deliberately omitted. Node output is
    restricted to account type, institution code, and country code; edge output
    contains the transaction UUID, direction, exact decimal amount, currency,
    and normalized UTC timestamp.
    """

    nodes = [
        {
            "account_id": _uuid_string(account_id),
            "attributes": {
                "account_type": graph.nodes[account_id].get("account_type"),
                "institution_code": graph.nodes[account_id].get("institution_code"),
                "country_code": graph.nodes[account_id].get("country_code"),
            },
        }
        for account_id in sorted(graph.nodes, key=str)
    ]

    edges = []
    for source, target, key, attributes in graph.edges(keys=True, data=True):
        transaction_id = attributes.get("transaction_id", key)
        amount = attributes["amount"]
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        edges.append(
            {
                "transaction_id": _uuid_string(transaction_id),
                "source": _uuid_string(source),
                "target": _uuid_string(target),
                "amount": _amount_string(amount),
                "currency": attributes["currency"],
                "timestamp": _utc_isoformat(attributes["occurred_at"]),
            }
        )
    edges.sort(
        key=lambda edge: (
            edge["transaction_id"],
            edge["source"],
            edge["target"],
        )
    )

    return {
        "schema_version": "1.0",
        "graph": {
            "dataset_id": str(graph.graph["dataset_id"])
            if graph.graph.get("dataset_id") is not None
            else None,
            "directed": True,
            "multigraph": True,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "filters": dict(graph.graph.get("filters", {})),
        },
        "nodes": nodes,
        "edges": edges,
    }
