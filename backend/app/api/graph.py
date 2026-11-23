"""Authenticated, dataset-scoped graph read APIs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.core.database import get_db
from app.graph.models import (
    DEFAULT_GRAPH_LIMITS,
    GraphFilters,
    GraphLimitExceeded,
)
from app.models import User
from app.schemas.graph import (
    AccountNetworkSummary,
    GraphEdgeData,
    GraphEdgeElement,
    GraphNeighborhoodResponse,
    GraphNodeData,
    GraphNodeElement,
    GraphOverviewResponse,
    GraphPath,
    GraphPathsResponse,
    GraphPathTransaction,
)
from app.schemas.pagination import PageResponse, page_response
from app.services.dataset_access import DatasetScopeNotFound
from app.services.graph_queries import (
    AccountGraphNotFound,
    account_neighborhood_graph,
    account_network_metrics,
    dataset_bounded_paths,
    graph_overview,
    list_graph_edges,
    list_graph_nodes,
)

router = APIRouter(tags=["Financial Graph"])


def _graph_filters(
    *,
    start_at: datetime | None,
    end_at: datetime | None,
    currency: str | None,
    minimum_amount: Decimal | None,
    maximum_amount: Decimal | None,
) -> GraphFilters:
    try:
        return GraphFilters(
            start_at=start_at,
            end_at=end_at,
            currency=currency,
            minimum_amount=minimum_amount,
            maximum_amount=maximum_amount,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _dataset_not_found(exc: DatasetScopeNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail="Dataset not found.")


def _account_not_found(exc: AccountGraphNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail="Account not found in dataset.")


def _graph_too_large(exc: GraphLimitExceeded) -> HTTPException:
    return HTTPException(
        status_code=413,
        detail="The requested graph result exceeds the supported graph limits.",
    )


def _node(row) -> GraphNodeElement:
    account_id = str(row.id)
    return GraphNodeElement(
        data=GraphNodeData(
            id=account_id,
            label=f"Account {account_id[:8]}",
            account_type=row.account_type,
            institution_code=row.institution_code,
            country_code=row.country_code,
        )
    )


def _node_from_attributes(account_id: UUID, attributes: dict) -> GraphNodeElement:
    account_key = str(account_id)
    return GraphNodeElement(
        data=GraphNodeData(
            id=account_key,
            label=f"Account {account_key[:8]}",
            account_type=attributes.get("account_type"),
            institution_code=attributes.get("institution_code"),
            country_code=attributes.get("country_code"),
        )
    )


def _edge(row) -> GraphEdgeElement:
    transaction_id = str(row.id)
    amount = row.amount if isinstance(row.amount, Decimal) else Decimal(str(row.amount))
    return GraphEdgeElement(
        data=GraphEdgeData(
            id=transaction_id,
            transaction_id=transaction_id,
            source=str(row.sender_account_id),
            target=str(row.receiver_account_id),
            amount=format(amount, "f"),
            currency=row.currency,
            occurred_at=row.occurred_at,
            transaction_type=row.transaction_type,
            channel=row.channel,
            status=row.status,
        )
    )


@router.get(
    "/datasets/{dataset_id}/graph/overview",
    response_model=GraphOverviewResponse,
    summary="Summarize an owned dataset graph",
)
def read_graph_overview(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    minimum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    maximum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
) -> GraphOverviewResponse:
    filters = _graph_filters(
        start_at=start_at,
        end_at=end_at,
        currency=currency,
        minimum_amount=minimum_amount,
        maximum_amount=maximum_amount,
    )
    try:
        return GraphOverviewResponse(
            **graph_overview(
                db, dataset_id=dataset_id, owner_id=actor.id, filters=filters
            )
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc


@router.get(
    "/datasets/{dataset_id}/graph/nodes",
    response_model=PageResponse[GraphNodeElement],
    summary="Page through graph accounts",
)
def read_graph_nodes(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    account_type: Annotated[str | None, Query(max_length=50)] = None,
    country_code: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    institution_code: Annotated[str | None, Query(max_length=80)] = None,
) -> PageResponse[GraphNodeElement]:
    try:
        rows, total = list_graph_nodes(
            db,
            dataset_id=dataset_id,
            owner_id=actor.id,
            page=page,
            page_size=page_size,
            account_type=account_type,
            country_code=country_code,
            institution_code=institution_code,
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    return page_response(
        items=[_node(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{dataset_id}/graph/edges",
    response_model=PageResponse[GraphEdgeElement],
    summary="Page through transaction edges",
)
def read_graph_edges(
    dataset_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    account_id: UUID | None = None,
    source_account_id: UUID | None = None,
    target_account_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    minimum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    maximum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    sort_by: Literal["occurred_at", "amount", "currency"] = "occurred_at",
    sort_order: Literal["asc", "desc"] = "desc",
) -> PageResponse[GraphEdgeElement]:
    filters = _graph_filters(
        start_at=start_at,
        end_at=end_at,
        currency=currency,
        minimum_amount=minimum_amount,
        maximum_amount=maximum_amount,
    )
    try:
        rows, total = list_graph_edges(
            db,
            dataset_id=dataset_id,
            owner_id=actor.id,
            filters=filters,
            page=page,
            page_size=page_size,
            account_id=account_id,
            source_account_id=source_account_id,
            target_account_id=target_account_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    return page_response(
        items=[_edge(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/datasets/{dataset_id}/accounts/{account_id}/network",
    response_model=AccountNetworkSummary,
    summary="Summarize an account's transaction network",
)
def read_account_network(
    dataset_id: UUID,
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    minimum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    maximum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
) -> AccountNetworkSummary:
    filters = _graph_filters(
        start_at=start_at,
        end_at=end_at,
        currency=currency,
        minimum_amount=minimum_amount,
        maximum_amount=maximum_amount,
    )
    try:
        metrics = account_network_metrics(
            db,
            dataset_id=dataset_id,
            owner_id=actor.id,
            account_id=account_id,
            filters=filters,
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    except AccountGraphNotFound as exc:
        raise _account_not_found(exc) from exc
    except GraphLimitExceeded as exc:
        raise _graph_too_large(exc) from exc
    return AccountNetworkSummary(dataset_id=dataset_id, **asdict(metrics))


@router.get(
    "/datasets/{dataset_id}/accounts/{account_id}/neighborhood",
    response_model=GraphNeighborhoodResponse,
    summary="Explore a bounded account neighborhood",
)
def read_account_neighborhood(
    dataset_id: UUID,
    account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    depth: Annotated[
        int,
        Query(ge=0, le=DEFAULT_GRAPH_LIMITS.max_neighborhood_depth),
    ] = 1,
    direction: Literal["incoming", "outgoing", "both"] = "both",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    minimum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    maximum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
) -> GraphNeighborhoodResponse:
    filters = _graph_filters(
        start_at=start_at,
        end_at=end_at,
        currency=currency,
        minimum_amount=minimum_amount,
        maximum_amount=maximum_amount,
    )
    try:
        graph = account_neighborhood_graph(
            db,
            dataset_id=dataset_id,
            owner_id=actor.id,
            account_id=account_id,
            depth=depth,
            direction=direction,
            filters=filters,
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    except AccountGraphNotFound as exc:
        raise _account_not_found(exc) from exc
    except GraphLimitExceeded as exc:
        raise _graph_too_large(exc) from exc
    return GraphNeighborhoodResponse(
        dataset_id=dataset_id,
        root_account_id=account_id,
        depth=depth,
        direction=direction,
        node_count=graph.number_of_nodes(),
        edge_count=graph.number_of_edges(),
        nodes=[
            _node_from_attributes(account_id, attributes)
            for account_id, attributes in sorted(
                graph.nodes(data=True), key=lambda item: str(item[0])
            )
        ],
        edges=[
            GraphEdgeElement(
                data=GraphEdgeData(
                    id=str(attributes.get("transaction_id", transaction_id)),
                    transaction_id=str(attributes.get("transaction_id", transaction_id)),
                    source=str(source),
                    target=str(target),
                    amount=format(attributes["amount"], "f"),
                    currency=attributes["currency"],
                    occurred_at=attributes["occurred_at"],
                    transaction_type=attributes.get("transaction_type"),
                    channel=attributes.get("channel"),
                    status=attributes.get("status"),
                )
            )
            for source, target, transaction_id, attributes in sorted(
                graph.edges(keys=True, data=True),
                key=lambda item: (str(item[0]), str(item[1]), str(item[2])),
            )
        ],
        filters=filters.metadata(),
    )


@router.get(
    "/datasets/{dataset_id}/graph/paths",
    response_model=GraphPathsResponse,
    summary="Find bounded transaction-level paths",
)
def read_graph_paths(
    dataset_id: UUID,
    source_account_id: UUID,
    target_account_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    actor: Annotated[User, Depends(get_current_user)],
    max_hops: Annotated[int, Query(ge=1, le=DEFAULT_GRAPH_LIMITS.max_path_hops)] = 4,
    max_paths: Annotated[int, Query(ge=1, le=DEFAULT_GRAPH_LIMITS.max_paths)] = 20,
    max_expansions: Annotated[
        int,
        Query(ge=1, le=DEFAULT_GRAPH_LIMITS.max_path_expansions),
    ] = DEFAULT_GRAPH_LIMITS.max_path_expansions,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    minimum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
    maximum_amount: Annotated[Decimal | None, Query(ge=0)] = None,
) -> GraphPathsResponse:
    filters = _graph_filters(
        start_at=start_at,
        end_at=end_at,
        currency=currency,
        minimum_amount=minimum_amount,
        maximum_amount=maximum_amount,
    )
    try:
        result = dataset_bounded_paths(
            db,
            dataset_id=dataset_id,
            owner_id=actor.id,
            source_account_id=source_account_id,
            target_account_id=target_account_id,
            filters=filters,
            max_hops=max_hops,
            max_paths=max_paths,
            max_expansions=max_expansions,
        )
    except DatasetScopeNotFound as exc:
        raise _dataset_not_found(exc) from exc
    except GraphLimitExceeded as exc:
        raise _graph_too_large(exc) from exc
    return GraphPathsResponse(
        dataset_id=dataset_id,
        source_account_id=source_account_id,
        target_account_id=target_account_id,
        source_found=result.source_found,
        target_found=result.target_found,
        paths=[
            GraphPath(
                account_ids=list(path.accounts),
                transactions=[
                    GraphPathTransaction(
                        transaction_id=edge.transaction_id,
                        source=edge.source,
                        target=edge.target,
                        amount=format(edge.amount, "f"),
                        currency=edge.currency,
                        occurred_at=edge.occurred_at,
                    )
                    for edge in path.transactions
                ],
            )
            for path in result.paths
        ],
        truncated=result.truncated,
        expanded_edges=result.expanded_edges,
    )
