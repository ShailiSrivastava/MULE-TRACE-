# Accounts and Transactions API

The API is available under `/api/v1` and requires a valid bearer access token from the Phase 4 authentication API. Every resource route is nested under a dataset ID. The caller must own that dataset; a dataset that is missing or belongs to another user returns the same `404` response. An owned dataset must already exist because dataset lifecycle endpoints are outside this API scope.

All collection endpoints use `page` (default `1`) and `page_size` (default `25`, maximum `100`). Responses include `items`, `page`, `page_size`, `total`, and `total_pages`. Empty result sets return `total_pages: 0`.

## Accounts

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/datasets/{dataset_id}/accounts` | Create an account |
| `GET` | `/api/v1/datasets/{dataset_id}/accounts` | List accounts |
| `GET` | `/api/v1/datasets/{dataset_id}/accounts/{account_id}` | Retrieve an account and its transaction count |
| `PATCH` | `/api/v1/datasets/{dataset_id}/accounts/{account_id}` | Update permitted account fields |

List filters are `account_type`, `country_code`, and exact `external_id`. Account creation accepts `external_id`, optional `account_type`, `institution_code`, `country_code`, and a JSON `metadata` object. Updates accept those same fields; dataset ownership and account IDs cannot be changed.

```http
POST /api/v1/datasets/9a77b3e8-3b52-4ee6-9bdd-f107fcb7ab22/accounts
Authorization: Bearer <access-token>
Content-Type: application/json
```

```json
{
  "external_id": "acct-10001",
  "account_type": "business",
  "institution_code": "BANK-01",
  "country_code": "US",
  "metadata": {"source": "case-file-12"}
}
```

The response includes the generated UUID, dataset ID, account fields, timestamps, and `transaction_count`. The count is calculated in the collection query and includes both incoming and outgoing transactions.

## Transactions

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/datasets/{dataset_id}/transactions` | Create a transaction |
| `GET` | `/api/v1/datasets/{dataset_id}/transactions` | List and filter transactions |
| `GET` | `/api/v1/datasets/{dataset_id}/transactions/{transaction_id}` | Retrieve a transaction |
| `PATCH` | `/api/v1/datasets/{dataset_id}/transactions/{transaction_id}` | Update permitted transaction fields |

Creation requires `sender_account_id`, `receiver_account_id`, positive `amount`, three-letter `currency`, and timezone-aware `occurred_at`. Optional fields are `external_transaction_id`, `transaction_type`, `channel`, `status`, and `metadata`. Currency codes are normalized to uppercase and timestamps to UTC. Monetary values allow up to 20 total digits and 6 decimal places.

List filters are:

- `account_id`: either sender or receiver.
- `sender_account_id` and `receiver_account_id`.
- Inclusive `min_amount` and `max_amount`.
- `currency`.
- Inclusive timezone-aware `start_at` and `end_at` timestamps.
- `sort_by`: `occurred_at` (default), `created_at`, `amount`, or `currency`.
- `sort_order`: `desc` (default) or `asc`.

The sender and receiver must be distinct accounts in the selected dataset. Each transaction is preserved independently, so repeated transfers between the same account pair are supported. Transaction IDs, dataset IDs, and sender/receiver IDs are immutable through `PATCH`.

```json
{
  "sender_account_id": "d9ea8787-2459-4233-a292-12a48d6670ef",
  "receiver_account_id": "662f31ce-68e1-47a7-b3e9-cc62af4836ed",
  "external_transaction_id": "bank-transfer-7788",
  "amount": "125.450000",
  "currency": "USD",
  "transaction_type": "transfer",
  "channel": "online",
  "status": "settled",
  "occurred_at": "2026-10-15T12:30:00+05:30",
  "metadata": {"source": "bank-export"}
}
```

A successful response has the same fields plus a generated transaction UUID and `created_at`; `occurred_at` is returned normalized to UTC. The `amount` is serialized as a decimal string to preserve precision.

Successful account and transaction creates/updates create an `audit_logs` event in the same database transaction. Audit details record the dataset ID and changed field names, not submitted account identifiers, amounts, metadata, or other values. Duplicate external IDs return `409 Conflict`; validation failures use the shared error envelope.
