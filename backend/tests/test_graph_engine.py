from __future__ import annotations

import json
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import networkx as nx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import DatabaseNotConfiguredError, get_engine
from app.core.model_base import Base
from app.graph import (
    AccountRecord,
    GraphFilters,
    GraphLimitExceeded,
    GraphLimits,
    GraphRecordError,
    TransactionRecord,
    account_metrics,
    build_transaction_graph,
    connected_components,
    extract_neighborhood,
    extract_subgraph,
    find_bounded_paths,
    network_metrics,
    serialize_graph,
    transaction_activity,
)
from app.graph.metrics import AccountNotInGraphError
from app.models import Account, Dataset, Transaction, User
from app.services.dataset_access import DatasetScopeNotFound
from app.services.graph import build_owned_dataset_graph

DATASET_ID = UUID("00000000-0000-0000-0000-000000000100")
OTHER_DATASET_ID = UUID("00000000-0000-0000-0000-000000000200")
START = datetime(2026, 11, 20, tzinfo=UTC)


def _account(index: int, *, dataset_id: UUID = DATASET_ID, **fields) -> AccountRecord:
    return AccountRecord(
        id=UUID(int=index),
        dataset_id=dataset_id,
        **fields,
    )


def _transaction(
    index: int,
    source: int,
    target: int,
    *,
    dataset_id: UUID = DATASET_ID,
    amount: Decimal | str = Decimal("10.00"),
    currency: str = "USD",
    occurred_at: datetime | None = None,
    **fields,
) -> TransactionRecord:
    return TransactionRecord(
        id=UUID(int=1_000 + index),
        dataset_id=dataset_id,
        sender_account_id=UUID(int=source),
        receiver_account_id=UUID(int=target),
        amount=Decimal(amount),
        currency=currency,
        occurred_at=occurred_at or START,
        **fields,
    )


def _graph(
    account_count: int,
    transactions: list[TransactionRecord] | None = None,
    *,
    filters: GraphFilters | None = None,
):
    return build_transaction_graph(
        DATASET_ID,
        [_account(index + 1) for index in range(account_count)],
        transactions or [],
        filters=filters,
    )


def test_empty_graph_and_isolated_accounts_have_zero_metrics():
    empty = _graph(0)
    assert isinstance(empty, nx.MultiDiGraph)
    assert network_metrics(empty).node_count == 0
    assert network_metrics(empty).edge_count == 0
    assert network_metrics(empty).directed_density == 0.0

    isolated_id = UUID(int=1)
    isolated = _graph(1)
    metrics = account_metrics(isolated, isolated_id)
    assert metrics.in_degree == metrics.out_degree == metrics.total_degree == 0
    assert metrics.incoming_transaction_count == 0
    assert metrics.outgoing_transaction_count == metrics.total_transaction_count == 0
    assert metrics.total_unique_counterparty_count == 0
    assert metrics.incoming_amount_by_currency == {}
    assert metrics.outgoing_amount_by_currency == {}
    with pytest.raises(AccountNotInGraphError):
        account_metrics(isolated, UUID(int=999))


def test_one_transaction_preserves_direction_and_account_attributes():
    accounts = [
        _account(1, account_type="business", country_code="US"),
        _account(2, account_type="personal", country_code="GB"),
        _account(3),
    ]
    transaction = _transaction(1, 1, 2, amount="12.340000")
    graph = build_transaction_graph(DATASET_ID, accounts, [transaction])

    assert set(graph.nodes) == {UUID(int=1), UUID(int=2), UUID(int=3)}
    assert graph.number_of_edges() == 1
    edge = graph.get_edge_data(UUID(int=1), UUID(int=2), UUID(int=1001))
    assert edge["transaction_id"] == transaction.id
    assert edge["amount"] == Decimal("12.340000")
    assert edge["currency"] == "USD"
    assert graph.in_degree(UUID(int=2)) == 1
    assert graph.out_degree(UUID(int=1)) == 1
    assert graph.nodes[UUID(int=1)]["account_type"] == "business"


def test_parallel_transactions_remain_individual_multidigraph_edges():
    transactions = [
        _transaction(1, 1, 2, amount="10.00"),
        _transaction(2, 1, 2, amount="25.50", currency="EUR"),
    ]
    graph = _graph(2, transactions)

    assert isinstance(graph, nx.MultiDiGraph)
    assert graph.number_of_edges() == 2
    assert set(graph.get_edge_data(UUID(int=1), UUID(int=2))) == {
        transactions[0].id,
        transactions[1].id,
    }
    metrics = account_metrics(graph, UUID(int=1))
    assert metrics.out_degree == metrics.outgoing_transaction_count == 2
    assert metrics.total_transaction_count == 2
    assert metrics.unique_outgoing_counterparty_count == 1
    assert metrics.outgoing_amount_by_currency == {
        "EUR": Decimal("25.50"),
        "USD": Decimal("10.00"),
    }


def test_builder_ignores_other_datasets_and_supports_model_forbidden_self_loop():
    accounts = [_account(1), _account(2), _account(3, dataset_id=OTHER_DATASET_ID)]
    transactions = [
        _transaction(1, 1, 2),
        _transaction(2, 1, 3, dataset_id=OTHER_DATASET_ID),
        _transaction(3, 1, 3),
        _transaction(4, 1, 1),
    ]
    graph = build_transaction_graph(DATASET_ID, accounts, transactions)

    assert set(graph.nodes) == {UUID(int=1), UUID(int=2)}
    assert graph.number_of_edges() == 2
    self_loop_metrics = account_metrics(graph, UUID(int=1))
    assert self_loop_metrics.in_degree == 1
    assert self_loop_metrics.out_degree == 2
    assert self_loop_metrics.total_degree == 3
    assert self_loop_metrics.total_transaction_count == 2
    assert self_loop_metrics.total_unique_counterparty_count == 1


def test_duplicate_transaction_ids_are_rejected_instead_of_overwriting_edges():
    first = _transaction(1, 1, 2)
    duplicate = TransactionRecord(
        id=first.id,
        dataset_id=first.dataset_id,
        sender_account_id=UUID(int=2),
        receiver_account_id=UUID(int=1),
        amount=first.amount,
        currency=first.currency,
        occurred_at=first.occurred_at,
    )
    with pytest.raises(GraphRecordError, match="Duplicate transaction ID"):
        _graph(2, [first, duplicate])


def test_time_filter_is_start_inclusive_and_end_exclusive():
    at_start = _transaction(1, 1, 2, occurred_at=START)
    between = _transaction(2, 1, 2, occurred_at=START + timedelta(hours=1))
    at_end = _transaction(3, 1, 2, occurred_at=START + timedelta(hours=2))
    filters = GraphFilters(
        start_at=START,
        end_at=START + timedelta(hours=2),
    )
    graph = _graph(2, [at_start, between, at_end], filters=filters)
    assert set(graph[UUID(int=1)][UUID(int=2)]) == {at_start.id, between.id}


def test_currency_and_inclusive_amount_bounds_filter_transactions():
    transactions = [
        _transaction(1, 1, 2, amount="10.00", currency="eur"),
        _transaction(2, 1, 2, amount="20.00", currency="EUR"),
        _transaction(3, 1, 2, amount="20.01", currency="EUR"),
        _transaction(4, 1, 2, amount="15.00", currency="USD"),
    ]
    graph = _graph(
        2,
        transactions,
        filters=GraphFilters(
            currency="eur",
            minimum_amount=Decimal("10.00"),
            maximum_amount=Decimal("20.00"),
        ),
    )
    assert set(graph[UUID(int=1)][UUID(int=2)]) == {
        transactions[0].id,
        transactions[1].id,
    }


def test_invalid_graph_filter_bounds_are_rejected():
    with pytest.raises(ValueError, match="earlier"):
        GraphFilters(start_at=START, end_at=START)
    with pytest.raises(ValueError, match="timezone"):
        GraphFilters(start_at=datetime(2026, 11, 20))
    with pytest.raises(ValueError, match="cannot exceed"):
        GraphFilters(minimum_amount="20", maximum_amount="10")
    with pytest.raises(TypeError, match="finite decimals"):
        GraphFilters(minimum_amount=0.1)


def test_account_filter_returns_induced_graph_with_no_phantom_nodes():
    transactions = [
        _transaction(1, 1, 2),
        _transaction(2, 2, 3),
        _transaction(3, 3, 1),
    ]
    graph = _graph(
        3,
        transactions,
        filters=GraphFilters(account_ids=frozenset({UUID(int=1), UUID(int=2)})),
    )
    assert set(graph.nodes) == {UUID(int=1), UUID(int=2)}
    assert graph.number_of_edges() == 1


def test_graph_construction_limits_are_enforced():
    limits = GraphLimits(max_accounts=2, max_transactions=1)
    with pytest.raises(GraphLimitExceeded, match="account limit"):
        build_transaction_graph(
            DATASET_ID,
            [_account(1), _account(2), _account(3)],
            [],
            limits=limits,
        )
    with pytest.raises(GraphLimitExceeded, match="transaction limit"):
        build_transaction_graph(
            DATASET_ID,
            [_account(1), _account(2)],
            [_transaction(1, 1, 2), _transaction(2, 1, 2)],
            limits=limits,
        )


def test_account_metrics_distinguish_parallel_edges_from_counterparties():
    transactions = [
        _transaction(1, 1, 2, amount="10", currency="USD"),
        _transaction(2, 1, 2, amount="2.25", currency="USD"),
        _transaction(3, 3, 1, amount="4", currency="EUR"),
        _transaction(4, 2, 1, amount="8", currency="EUR"),
    ]
    metrics = account_metrics(_graph(3, transactions), UUID(int=1))

    assert metrics.in_degree == 2
    assert metrics.out_degree == 2
    assert metrics.total_degree == 4
    assert metrics.incoming_transaction_count == 2
    assert metrics.outgoing_transaction_count == 2
    assert metrics.total_transaction_count == 4
    assert metrics.unique_incoming_counterparty_count == 2
    assert metrics.unique_outgoing_counterparty_count == 1
    assert metrics.total_unique_counterparty_count == 2
    assert metrics.incoming_amount_by_currency == {"EUR": Decimal(12)}
    assert metrics.outgoing_amount_by_currency == {"USD": Decimal("12.25")}


def test_time_window_activity_is_half_open_and_counts_parallel_edges():
    transactions = [
        _transaction(1, 1, 2, occurred_at=START),
        _transaction(2, 1, 2, occurred_at=START + timedelta(hours=1)),
        _transaction(3, 2, 1, occurred_at=START + timedelta(hours=2)),
    ]
    activity = transaction_activity(
        _graph(2, transactions),
        UUID(int=1),
        start_at=START,
        end_at=START + timedelta(hours=2),
    )
    assert activity.incoming_transaction_count == 0
    assert activity.outgoing_transaction_count == 2
    assert activity.total_transaction_count == 2


def test_connected_components_density_and_network_counts():
    transactions = [
        _transaction(1, 1, 2),
        _transaction(2, 1, 2),  # Parallel edge does not increase simple density.
        _transaction(3, 2, 1),
        _transaction(4, 2, 3),
    ]
    graph = _graph(4, transactions)
    components = connected_components(graph)
    metrics = network_metrics(graph)

    assert [component.size for component in components["weak"]] == [3, 1]
    assert [set(component.accounts) for component in components["strong"]] == [
        {UUID(int=1), UUID(int=2)},
        {UUID(int=3)},
        {UUID(int=4)},
    ]
    assert metrics.node_count == 4
    assert metrics.edge_count == 4
    assert metrics.directed_density == pytest.approx(3 / 12)
    assert network_metrics(_graph(1)).directed_density == 0


def test_subgraph_and_neighborhood_depth_and_direction():
    transactions = [
        _transaction(1, 1, 2),
        _transaction(2, 2, 3),
        _transaction(3, 4, 2),
    ]
    graph = _graph(4, transactions)
    subgraph = extract_subgraph(graph, {UUID(int=1), UUID(int=2), UUID(int=9)})
    assert set(subgraph.nodes) == {UUID(int=1), UUID(int=2)}
    assert subgraph.number_of_edges() == 1

    depth_one_both = extract_neighborhood(graph, UUID(int=2), depth=1)
    assert set(depth_one_both.nodes) == {
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
    }
    outgoing = extract_neighborhood(graph, UUID(int=2), depth=1, direction="outgoing")
    assert set(outgoing.nodes) == {UUID(int=2), UUID(int=3)}
    at_root = extract_neighborhood(graph, UUID(int=2), depth=0)
    assert set(at_root.nodes) == {UUID(int=2)}
    missing = extract_neighborhood(graph, UUID(int=99), depth=1)
    assert missing.number_of_nodes() == missing.number_of_edges() == 0
    with pytest.raises(GraphLimitExceeded):
        extract_neighborhood(
            graph,
            UUID(int=1),
            depth=6,
            limits=GraphLimits(max_neighborhood_depth=5),
        )


def test_bounded_paths_preserve_parallel_transaction_edges_and_direction():
    transactions = [
        _transaction(1, 1, 2, amount="1"),
        _transaction(2, 1, 2, amount="2"),
        _transaction(3, 2, 3, amount="3"),
        _transaction(4, 3, 1, amount="4"),
        _transaction(5, 1, 1, amount="5"),
    ]
    graph = _graph(3, transactions)
    result = find_bounded_paths(
        graph, UUID(int=1), UUID(int=3), max_hops=2, max_paths=10
    )

    assert result.source_found and result.target_found
    assert len(result.paths) == 2
    assert {path.transactions[0].transaction_id for path in result.paths} == {
        transactions[0].id,
        transactions[1].id,
    }
    assert all(
        path.transactions[-1].transaction_id == transactions[2].id
        for path in result.paths
    )
    assert all(
        path.accounts == (UUID(int=1), UUID(int=2), UUID(int=3))
        for path in result.paths
    )
    assert all(
        len(path.accounts) == len(path.transactions) + 1 for path in result.paths
    )
    assert all(
        edge.source == path.accounts[index] and edge.target == path.accounts[index + 1]
        for path in result.paths
        for index, edge in enumerate(path.transactions)
    )


def test_direct_path_returns_exactly_one_transaction_reference():
    transaction = _transaction(1, 1, 2, amount="9.75", currency="GBP")
    result = find_bounded_paths(
        _graph(2, [transaction]),
        UUID(int=1),
        UUID(int=2),
        max_hops=1,
    )
    assert len(result.paths) == 1
    path = result.paths[0]
    assert path.accounts == (UUID(int=1), UUID(int=2))
    assert len(path.transactions) == 1
    assert path.transactions[0].transaction_id == transaction.id
    assert path.transactions[0].amount == Decimal("9.75")
    assert path.transactions[0].currency == "GBP"


def test_paths_report_missing_and_unreachable_accounts():
    graph = _graph(3, [_transaction(1, 1, 2)])
    unreachable = find_bounded_paths(graph, UUID(int=1), UUID(int=3))
    assert unreachable.source_found and unreachable.target_found
    assert unreachable.paths == ()
    missing_source = find_bounded_paths(graph, UUID(int=99), UUID(int=2))
    assert not missing_source.source_found and missing_source.target_found
    assert missing_source.paths == ()
    missing_target = find_bounded_paths(graph, UUID(int=1), UUID(int=99))
    assert missing_target.source_found and not missing_target.target_found
    assert missing_target.paths == ()
    assert find_bounded_paths(graph, UUID(int=1), UUID(int=1)).paths == ()


def test_path_hop_result_and_expansion_limits_are_enforced():
    graph = _graph(
        4,
        [
            _transaction(1, 1, 2),
            _transaction(2, 1, 3),
            _transaction(3, 3, 4),
        ],
    )
    with pytest.raises(GraphLimitExceeded):
        find_bounded_paths(
            graph,
            UUID(int=1),
            UUID(int=4),
            max_hops=9,
        )
    result_limit = find_bounded_paths(
        _graph(3, [_transaction(1, 1, 3), _transaction(2, 1, 3)]),
        UUID(int=1),
        UUID(int=3),
        max_hops=1,
        max_paths=1,
    )
    assert len(result_limit.paths) == 1
    assert result_limit.truncated
    expansion_limit = find_bounded_paths(
        graph,
        UUID(int=1),
        UUID(int=4),
        max_hops=3,
        max_expansions=1,
    )
    assert expansion_limit.paths == ()
    assert expansion_limit.truncated
    assert expansion_limit.expanded_edges == 1


def test_stable_json_serialization_preserves_exact_amounts_and_omits_metadata():
    high_precision = Decimal("12345678901234.123456")
    transaction = _transaction(
        1,
        1,
        2,
        amount=high_precision,
        occurred_at=datetime(2026, 11, 20, 12, tzinfo=UTC)
        + timedelta(hours=5, minutes=30),
    )
    graph = build_transaction_graph(
        DATASET_ID,
        [
            _account(
                1,
                account_type="business",
                country_code="IN",
            ),
            _account(2),
        ],
        [transaction, _transaction(2, 1, 2, amount="1.00")],
    )
    graph.nodes[UUID(int=1)]["metadata_json"] = {"secret": "do-not-serialize"}
    graph.nodes[UUID(int=1)]["external_id"] = "sensitive-external-id"
    graph.edges[UUID(int=1), UUID(int=2), transaction.id]["metadata_json"] = {
        "secret": "do-not-serialize"
    }

    payload = serialize_graph(graph)
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["graph"]["dataset_id"] == str(DATASET_ID)
    assert payload["graph"]["node_count"] == 2
    assert payload["graph"]["edge_count"] == 2
    assert len(payload["edges"]) == 2
    edge = next(
        item
        for item in payload["edges"]
        if item["transaction_id"] == str(transaction.id)
    )
    assert edge["amount"] == "12345678901234.123456"
    assert edge["timestamp"] == "2026-11-20T17:30:00Z"
    assert "do-not-serialize" not in encoded
    assert "sensitive-external-id" not in encoded
    assert payload["nodes"][0]["attributes"]["account_type"] == "business"


@pytest.fixture
def graph_db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_database_loader_is_owner_scoped_filtered_and_includes_isolates(graph_db):
    owner = User(email="graph-owner@example.com", password_hash="test-hash")
    other_owner = User(email="graph-other@example.com", password_hash="test-hash")
    graph_db.add_all([owner, other_owner])
    graph_db.flush()
    dataset = Dataset(owner_id=owner.id, name="Graph dataset")
    other_dataset = Dataset(owner_id=other_owner.id, name="Other graph dataset")
    graph_db.add_all([dataset, other_dataset])
    graph_db.flush()
    account_a = Account(dataset_id=dataset.id, external_id="a", account_type="business")
    account_b = Account(dataset_id=dataset.id, external_id="b")
    isolated = Account(dataset_id=dataset.id, external_id="isolated")
    other_account = Account(dataset_id=other_dataset.id, external_id="other")
    other_receiver = Account(dataset_id=other_dataset.id, external_id="other-2")
    graph_db.add_all([account_a, account_b, isolated, other_account, other_receiver])
    graph_db.flush()
    graph_db.add_all(
        [
            Transaction(
                dataset_id=dataset.id,
                sender_account_id=account_a.id,
                receiver_account_id=account_b.id,
                amount=Decimal("5.25"),
                currency="USD",
                occurred_at=START,
            ),
            Transaction(
                dataset_id=other_dataset.id,
                sender_account_id=other_account.id,
                receiver_account_id=other_receiver.id,
                amount=Decimal("99.00"),
                currency="USD",
                occurred_at=START,
            ),
        ]
    )
    graph_db.flush()

    graph = build_owned_dataset_graph(
        graph_db,
        dataset_id=dataset.id,
        owner_id=owner.id,
    )
    assert set(graph.nodes) == {account_a.id, account_b.id, isolated.id}
    assert graph.number_of_edges() == 1
    assert all(data["dataset_id"] == dataset.id for _, data in graph.nodes(data=True))
    assert all(
        data["dataset_id"] == dataset.id for _, _, data in graph.edges(data=True)
    )

    filtered = build_owned_dataset_graph(
        graph_db,
        dataset_id=dataset.id,
        owner_id=owner.id,
        filters=GraphFilters(account_ids=frozenset({account_a.id})),
    )
    assert set(filtered.nodes) == {account_a.id}
    assert filtered.number_of_edges() == 0

    inclusive_time_and_amount = build_owned_dataset_graph(
        graph_db,
        dataset_id=dataset.id,
        owner_id=owner.id,
        filters=GraphFilters(
            start_at=START,
            end_at=START + timedelta(seconds=1),
            currency="usd",
            minimum_amount=Decimal("5.25"),
            maximum_amount=Decimal("5.25"),
        ),
    )
    assert inclusive_time_and_amount.number_of_edges() == 1
    exclusive_end = build_owned_dataset_graph(
        graph_db,
        dataset_id=dataset.id,
        owner_id=owner.id,
        filters=GraphFilters(
            start_at=START + timedelta(seconds=1),
            end_at=START + timedelta(seconds=2),
        ),
    )
    assert exclusive_end.number_of_edges() == 0

    with pytest.raises(DatasetScopeNotFound):
        build_owned_dataset_graph(
            graph_db,
            dataset_id=dataset.id,
            owner_id=other_owner.id,
        )


def test_dataset_graph_ownership_error_is_hidden(graph_db):
    owner = User(email="graph-owner-2@example.com", password_hash="test-hash")
    other_owner = User(email="graph-other-2@example.com", password_hash="test-hash")
    graph_db.add_all([owner, other_owner])
    graph_db.flush()
    dataset = Dataset(owner_id=owner.id, name="Private graph")
    graph_db.add(dataset)
    graph_db.flush()
    with pytest.raises(DatasetScopeNotFound):
        build_owned_dataset_graph(
            graph_db,
            dataset_id=dataset.id,
            owner_id=other_owner.id,
        )


@pytest.mark.integration
def test_postgres_graph_loader_uses_the_dataset_scope_and_rolls_back():
    try:
        engine = get_engine()
    except DatabaseNotConfiguredError as exc:
        pytest.skip(f"PostgreSQL is not configured: {exc}")
    if engine.dialect.name != "postgresql":
        pytest.skip("The configured database is not PostgreSQL.")

    try:
        connection = engine.connect()
    except OperationalError:
        pytest.fail(
            "Configured PostgreSQL is unreachable for the graph integration test.",
            pytrace=False,
        )
    outer_transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        owner = User(email=f"graph-{uuid4()}@example.com", password_hash="test-hash")
        other_owner = User(
            email=f"graph-{uuid4()}@example.com", password_hash="test-hash"
        )
        session.add_all([owner, other_owner])
        session.flush()
        dataset = Dataset(owner_id=owner.id, name=f"Graph {uuid4()}")
        other_dataset = Dataset(owner_id=other_owner.id, name=f"Other {uuid4()}")
        session.add_all([dataset, other_dataset])
        session.flush()
        account_a = Account(dataset_id=dataset.id, external_id="a")
        account_b = Account(dataset_id=dataset.id, external_id="b")
        other_a = Account(dataset_id=other_dataset.id, external_id="a")
        other_b = Account(dataset_id=other_dataset.id, external_id="b")
        session.add_all([account_a, account_b, other_a, other_b])
        session.flush()
        session.add_all(
            [
                Transaction(
                    dataset_id=dataset.id,
                    sender_account_id=account_a.id,
                    receiver_account_id=account_b.id,
                    amount=Decimal("1.25"),
                    currency="USD",
                    occurred_at=START,
                ),
                Transaction(
                    dataset_id=other_dataset.id,
                    sender_account_id=other_a.id,
                    receiver_account_id=other_b.id,
                    amount=Decimal("999.00"),
                    currency="USD",
                    occurred_at=START,
                ),
            ]
        )
        session.flush()

        graph = build_owned_dataset_graph(
            session,
            dataset_id=dataset.id,
            owner_id=owner.id,
            filters=GraphFilters(minimum_amount=Decimal("1.25")),
        )
        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1
        assert all(
            data["dataset_id"] == dataset.id for _, data in graph.nodes(data=True)
        )
        with pytest.raises(DatasetScopeNotFound):
            build_owned_dataset_graph(
                session,
                dataset_id=dataset.id,
                owner_id=other_owner.id,
            )
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()
