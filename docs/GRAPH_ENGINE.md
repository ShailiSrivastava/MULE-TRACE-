# MuleTrace Financial Transaction Graph Engine

The graph engine is a backend library in `backend/app/graph/`. It converts one dataset's account and transaction rows into a directed NetworkX `MultiDiGraph`. Database reads live in `app/services/graph.py`; graph algorithms accept in-memory graph objects and do not depend on FastAPI or SQLAlchemy. This phase adds no graph API or frontend behavior.

## Graph data model

- Each account UUID is a node key. Nodes carry their UUID, dataset UUID, account type, institution code, and country code.
- Each transaction UUID is an edge key from sender to receiver. Edge attributes preserve transaction UUID, dataset UUID, `Decimal` amount, uppercase currency, UTC timestamp, transaction type, channel, and status.
- `MultiDiGraph` keeps repeated transactions between the same account pair as distinct keyed edges. Accounts with no matching transaction stay as isolated nodes.
- The database schema prohibits self-transfers. The pure graph module can represent a self-loop supplied by a non-database source; its algorithms remain bounded and account for that edge explicitly.
- Source rows are copied into graph attributes; graph construction does not mutate or commit database records. External account identifiers and flexible account metadata are not loaded for graph display.

## Database construction and ownership

`build_owned_dataset_graph(db, dataset_id, owner_id, filters=...)` first checks ownership with the shared dataset-scope service. It then issues one selected-column account query and one selected-column transaction query, each restricted to that dataset and bounded to one row above the configured maximum. Queries are ordered for repeatable construction and use batched result fetching. A dataset not owned by the caller raises the same `DatasetScopeNotFound` used by the dataset services.

Default limits are 100,000 accounts and 500,000 transactions per graph. Oversized graph construction raises `GraphLimitExceeded` rather than returning a silently partial graph. `GraphLimits` can be supplied by trusted internal callers to set lower bounds for tests or specialized workloads.

## Filtering semantics

`GraphFilters` supports time bounds, currency, minimum/maximum amounts, and account IDs:

- Time filtering is half-open: `occurred_at >= start_at` and `occurred_at < end_at`. Thus the start is included and the end is excluded. Supplied timestamps must be timezone-aware and are normalized to UTC.
- Currency matching is case-insensitive at input and exact after uppercase normalization.
- Minimum and maximum amounts are inclusive (`amount >= minimum_amount`, `amount <= maximum_amount`). Amounts are `Decimal`; float filter values are rejected to avoid binary rounding.
- Account IDs select an induced subgraph: only selected accounts from the requested dataset are included, and a transaction is retained only if both endpoints are selected. Unknown or foreign-dataset IDs do not create nodes or reveal records.
- Filtering transactions does not remove otherwise selected accounts, so accounts with no matching edges remain isolated nodes.

## Account metrics

`account_metrics(graph, account_id)` returns:

- In-degree, out-degree, and total degree. Each parallel transaction contributes one to its direction; total degree is in-degree plus out-degree.
- Incoming, outgoing, and total transaction counts. Total count counts distinct transaction edge keys, so a self-loop is one transaction even though it contributes once to in-degree and once to out-degree.
- Unique incoming, outgoing, and combined counterparty counts. Parallel transfers to the same account count as one counterparty; a self-loop is not treated as an account's own counterparty.
- Incoming and outgoing amount totals grouped by currency. Totals use `Decimal`; different currencies are never combined.

`transaction_activity(graph, account_id, start_at, end_at)` counts incoming, outgoing, and distinct total transactions in the half-open UTC interval `[start_at, end_at)`. Requests for a missing account raise `AccountNotInGraphError`; isolated graph nodes return zero counts and empty amount maps.

## Network analysis

- `connected_components` returns weakly connected components (ignoring direction) and strongly connected components (mutual directed reachability). Each component includes sorted account UUID membership and a size; results are deterministically ordered by descending size and then membership.
- `network_metrics` returns node and transaction-edge counts plus directed simple-topology density. Density is the number of distinct directed non-self account pairs with at least one transaction divided by `n * (n - 1)`. Parallel edges do not increase density; self-loops are excluded; density is zero for fewer than two nodes.
- `extract_subgraph` returns a copied induced subgraph over the selected account IDs.
- `extract_neighborhood` returns accounts within a bounded hop depth. Direction can be `incoming`, `outgoing`, or `both`; depth zero returns only the root, and a missing root returns an empty graph. The default maximum neighborhood depth is five.

## Multi-hop paths

`find_bounded_paths(graph, source, target, ...)` searches only directed, simple account paths. Every returned path contains ordered account UUIDs and ordered transaction references with each edge's transaction UUID, source, target, exact amount, currency, and timestamp. Parallel transactions between the same accounts produce distinct paths.

Default search limits are four hops, 20 returned paths, and 100,000 expanded edges. Hard maxima are eight hops and 100 paths. The search stops at the expansion bound and sets `truncated`; it also sets `truncated` when an additional path exists beyond the returned path limit. Cycles and self-loops are not traversed because an account cannot appear twice in one path. Missing source/target IDs are reported by `source_found` and `target_found`; unreachable nodes return no paths. A source equal to its target returns no zero-length path. This is path enumeration only; it does not identify suspicious cycles or assign risk.

## Stable serialization

`serialize_graph(graph)` produces a NetworkX-independent JSON-ready dictionary with schema version, dataset ID, directed/multigraph flags, counts, filter metadata, sorted nodes, and sorted edges. Node output is allowlisted to account UUID, account type, institution code, and country code. It does not serialize account external IDs, account metadata, or arbitrary graph attributes.

Each edge serializes transaction UUID, source, target, amount as a fixed-point decimal string, currency, and timestamp as a UTC ISO 8601 string ending in `Z`. This preserves monetary precision without JSON floating-point conversion and retains every parallel transaction. The stable shape is intended for a future API contract; no endpoint is added in this phase.

## Performance limits and future scaling

NetworkX graphs reside in process memory, so the engine is bounded to 100,000 nodes and 500,000 edges by default. Path expansion and neighborhood depth have separate limits to bound combinatorial traversal. These limits are safe starting points, not capacity guarantees for all deployment hardware. Larger workloads may need asynchronous graph construction, precomputed graph snapshots, or a specialized graph/columnar backend in a later phase; this implementation intentionally adds no Neo4j, Kafka, worker queue, or distributed graph processing.
