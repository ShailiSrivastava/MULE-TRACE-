# Datasets, Synthetic Data, and CSV Imports

All routes require an active bearer token. A caller can see or change only datasets whose `owner_id` matches the authenticated user. A missing dataset and another user's dataset return the same `404` response. Dataset deletion is not provided.

## Dataset lifecycle

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/datasets` | Create a dataset owned by the caller |
| `GET` | `/api/v1/datasets` | List the caller's datasets |
| `GET` | `/api/v1/datasets/{dataset_id}` | Retrieve an owned dataset |
| `PATCH` | `/api/v1/datasets/{dataset_id}` | Update name, description, source, or metadata |

Create example:

```json
{
  "name": "October investigation",
  "description": "Transfers supplied for case review",
  "source": "bank-export",
  "metadata": {"case_reference": "CASE-104"}
}
```

Dataset responses include `account_count` and `transaction_count`, calculated with aggregate subqueries. Names are unique per owner. The API does not accept `owner_id`, `status`, or `is_synthetic` from clients. Metadata must be a JSON object no larger than 64 KiB.

## Synthetic data

`POST /api/v1/datasets/{dataset_id}/synthetic-data` generates accounts and transactions synchronously in an empty owned dataset. Defaults are 100 accounts, 1,000 transactions, a 30-day UTC range, USD/EUR/GBP, seed `42`, and all supported patterns. Limits are 2,000 accounts and 20,000 transactions. The range must span at least 30 minutes when patterns are requested.

Example:

```json
{
  "account_count": 25,
  "transaction_count": 200,
  "start_at": "2026-10-01T00:00:00Z",
  "end_at": "2026-10-31T23:59:59Z",
  "currencies": ["USD", "EUR"],
  "seed": 1042,
  "patterns": ["rapid_successive", "fan_in", "circular", "multi_hop"]
}
```

Supported patterns are `rapid_successive`, `fan_in`, `fan_out`, `circular`, `multi_hop`, `unusual_amount`, and `unusual_frequency`. The same dataset ID and seed produce the same generated IDs and values. A dataset must be empty before generation; a second generation attempt returns `409`.

Generated labels are written only to `ground_truth_labels` with `source="synthetic"` and scheme `muletrace_synthetic_v1`. They are not detection alerts and do not establish that real-world financial crime occurred. Generated records are marked synthetic in their metadata, and the dataset is marked `is_synthetic=true`. CSV imports are refused for synthetic datasets so that this flag stays meaningful.

## Canonical CSV formats

Uploads use canonical headers. Header names are trimmed and case-insensitive; unsupported or duplicate columns fail the import. The file is parsed as UTF-8 (a UTF-8 BOM is accepted). MIME type is ignored. `metadata_json` is an optional JSON object encoded in one CSV cell.

Account CSV requires `external_id`. Optional columns are `account_type`, `institution_code`, `country_code`, and `metadata_json`. Example: [accounts.csv](examples/accounts.csv).

Transaction CSV requires `external_transaction_id`, `sender_external_id`, `receiver_external_id`, `amount`, `currency`, and `occurred_at`. Optional columns are `transaction_type`, `channel`, `status`, and `metadata_json`. The external account IDs must resolve to distinct accounts in the same dataset. Amounts must be positive with up to 20 digits and 6 decimal places. Timestamps must include a timezone offset and are normalized to UTC. Example: [transactions.csv](examples/transactions.csv).

## Import endpoints and result semantics

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/datasets/{dataset_id}/imports/accounts` | Import account CSV |
| `POST` | `/api/v1/datasets/{dataset_id}/imports/transactions` | Import transaction CSV |
| `GET` | `/api/v1/datasets/{dataset_id}/imports` | Paginated import history; optional `status=pending`, `completed`, or `failed` filter |
| `GET` | `/api/v1/datasets/{dataset_id}/imports/{import_job_id}` | Retrieve import tracking details |

Upload with multipart field name `file`. A processed upload returns an import result containing job ID, sanitized filename, status, row counts, error summary, and row-level issues. Validation failures are represented by `status="failed"` and do not expose submitted cell contents. A malformed header fails the job and reports its header error at row 1.

Each file is one atomic data batch. If any non-duplicate data row is invalid, no valid rows from that file are committed. Such a batch has `accepted_rows=0`; invalid rows count as rejected, and otherwise valid rows rolled back with the batch count as skipped. Blank rows and duplicates are also counted as skipped. Existing or repeated-in-file external IDs are skipped and counted as duplicates, making retries safe; existing rows are never overwritten. Successful accepted rows, the completed import job, and its audit event commit together. A database conflict rolls back the full data batch and records a failed job.

Upload size defaults to 10 MiB and the data-row limit defaults to 10,000. Configure `CSV_MAX_UPLOAD_BYTES` and `CSV_MAX_ROWS` through the environment. Uploads use FastAPI's spooled file handling and are streamed through the CSV parser; the client filename is reduced to a basename and is never used as a filesystem path. Imported account and transaction metadata receives a server-owned `muletrace_import` object with the import job ID and sanitized basename; CSV input cannot set this reserved property. No submitted financial data is written to logs or audit details.
