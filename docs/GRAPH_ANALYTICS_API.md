# MuleTrace Graph and Analytics API

All endpoints below use the versioned `/api/v1` prefix and require a valid
Bearer access token. Dataset reads are scoped to the authenticated user's owned
dataset; cross-user datasets return `404`.

## Graph endpoints

| Endpoint | Purpose |
|---|---|
| `GET /datasets/{dataset_id}/graph/overview` | Account and transaction counts, directed density, and transaction totals grouped by currency. |
| `GET /datasets/{dataset_id}/graph/nodes` | Paginated account nodes, with optional `account_type`, `country_code`, and `institution_code` filters. |
| `GET /datasets/{dataset_id}/graph/edges` | Paginated transaction edges, with endpoint, amount, currency, timestamp, and sort filters. |
| `GET /datasets/{dataset_id}/accounts/{account_id}/network` | Directional transaction counts, unique counterparties, and currency-separated amounts. |
| `GET /datasets/{dataset_id}/accounts/{account_id}/neighborhood` | A bounded induced account subgraph; supports `depth` and `direction=incoming\|outgoing\|both`. |
| `GET /datasets/{dataset_id}/graph/paths` | Bounded simple directed account paths, preserving each transaction in a path. |

Graph transaction filters include `start_at`, `end_at`, `currency`,
`minimum_amount`, and `maximum_amount`. Timestamp windows are UTC-aware and
half-open (`start_at <= occurred_at < end_at`). Currency totals are never
combined across currencies. Monetary edge values are decimal strings.

Graph nodes and edges use Cytoscape element DTOs. Account UUIDs are node IDs;
transaction UUIDs are edge IDs; edge `source` and `target` values are account
UUIDs. Parallel transactions remain separate edge elements.

```json
{
  "data": {
    "id": "transaction-uuid",
    "transaction_id": "transaction-uuid",
    "source": "sender-account-uuid",
    "target": "receiver-account-uuid",
    "amount": "10.250000",
    "currency": "USD",
    "occurred_at": "2026-11-20T12:00:00Z",
    "transaction_type": "transfer",
    "channel": "online",
    "status": "settled"
  }
}
```

Paginated endpoints return `items`, `page`, `page_size`, `total`, and
`total_pages`. Page size is limited to 100. Graph traversal uses the Phase 7
limits: at most 100,000 accounts, 500,000 transactions, 5 neighborhood hops,
8 path hops, 100 returned paths, and 100,000 examined path edges.

## Analytics endpoints

| Endpoint | Purpose |
|---|---|
| `GET /datasets/{dataset_id}/analytics` | Dataset metadata, account/transaction counts, currency-separated transaction totals, existing finding/risk summary, and latest persisted analysis-job progress. |
| `GET /datasets/{dataset_id}/accounts/{account_id}/analytics` | Account network totals, linked/open finding counts, and its latest persisted account-risk assessment (or `null`). |
| `GET /datasets/{dataset_id}/analytics/risk-distribution` | Counts and average scores by the latest persisted account risk level, unscored account count, and existing finding risk distribution. |
| `GET /datasets/{dataset_id}/analytics/ml/models` | Paginated model registry metadata trained on this dataset. |
| `GET /datasets/{dataset_id}/analytics/ml/anomalies` | Paginated persisted findings with category `ml_anomaly`. |

Existing endpoints remain the canonical APIs for findings and evidence
(`GET /datasets/{dataset_id}/findings` and
`GET /datasets/{dataset_id}/findings/{finding_id}`), risk summary and account
risk (`GET /datasets/{dataset_id}/risk-summary` and
`GET /datasets/{dataset_id}/accounts/{account_id}/risk`), and job status
(`GET /datasets/{dataset_id}/analysis/{job_id}`). They share the same dataset
ownership checks and UUID identifiers.

The API reports only persisted data. Empty model registries, unscored accounts,
empty datasets, and absent analysis jobs remain empty or `null`; no fallback
metrics or model probabilities are generated.
