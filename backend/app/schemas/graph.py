"""Stable graph API DTOs for Cytoscape and other clients."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GraphCurrencyTotal(BaseModel):
    currency: str
    transaction_count: int = Field(ge=0)
    total_amount: Decimal


class GraphOverviewResponse(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: UUID
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    directed_density: float = Field(ge=0, le=1)
    currency_totals: list[GraphCurrencyTotal]
    filters: dict[str, str | bool | None]


class GraphNodeData(BaseModel):
    """Cytoscape node data; IDs are the same UUIDs used by account APIs."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    account_type: str | None
    institution_code: str | None
    country_code: str | None


class GraphNodeElement(BaseModel):
    data: GraphNodeData


class GraphEdgeData(BaseModel):
    """One transaction per edge; parallel transfers keep distinct IDs."""

    model_config = ConfigDict(extra="forbid")

    id: str
    transaction_id: str
    source: str
    target: str
    amount: str
    currency: str
    occurred_at: datetime
    transaction_type: str | None
    channel: str | None
    status: str | None


class GraphEdgeElement(BaseModel):
    data: GraphEdgeData


class AccountNetworkSummary(BaseModel):
    dataset_id: UUID
    account_id: UUID
    in_degree: int = Field(ge=0)
    out_degree: int = Field(ge=0)
    total_degree: int = Field(ge=0)
    incoming_transaction_count: int = Field(ge=0)
    outgoing_transaction_count: int = Field(ge=0)
    total_transaction_count: int = Field(ge=0)
    unique_incoming_counterparty_count: int = Field(ge=0)
    unique_outgoing_counterparty_count: int = Field(ge=0)
    total_unique_counterparty_count: int = Field(ge=0)
    incoming_amount_by_currency: dict[str, Decimal]
    outgoing_amount_by_currency: dict[str, Decimal]


class GraphNeighborhoodResponse(BaseModel):
    dataset_id: UUID
    root_account_id: UUID
    depth: int = Field(ge=0)
    direction: Literal["incoming", "outgoing", "both"]
    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    nodes: list[GraphNodeElement]
    edges: list[GraphEdgeElement]
    filters: dict[str, str | bool | None]


class GraphPathTransaction(BaseModel):
    transaction_id: UUID
    source: UUID
    target: UUID
    amount: str
    currency: str
    occurred_at: datetime


class GraphPath(BaseModel):
    account_ids: list[UUID]
    transactions: list[GraphPathTransaction]


class GraphPathsResponse(BaseModel):
    dataset_id: UUID
    source_account_id: UUID
    target_account_id: UUID
    source_found: bool
    target_found: bool
    paths: list[GraphPath]
    truncated: bool
    expanded_edges: int = Field(ge=0)
