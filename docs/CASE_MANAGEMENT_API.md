# MuleTrace Investigation Case API

All routes are under `/api/v1` and require a bearer access token. JSON errors
use the standard `{ "error": { "code", "message", "request_id" } }`
envelope. UUIDs and timestamps use the existing API conventions; timestamps
serialize as UTC-aware ISO 8601 values.

## Access rules

- The dataset owner can create and access cases in that dataset.
- A case assignment to an active `INVESTIGATOR` or `ADMIN` grants access to
  that case and its linked evidence only. It does not grant access to unrelated
  accounts, transactions, findings, or other cases in the dataset.
- Case lifecycle, assignment, and evidence-link mutations require `INVESTIGATOR`
  or `ADMIN`.
- Any authorized case reader may create a note. An analyst may edit or archive
  notes they authored; investigators and administrators may edit or archive
  notes in cases they can access.
- Cross-dataset accounts and findings are returned as not found.
- Case deletion and note deletion archive records. Account and finding links
  are soft-unlinked, preserving link-time evidence and timeline records.

## Cases

| Method and route | Purpose |
|---|---|
| `POST /datasets/{dataset_id}/cases` | Create a case. |
| `GET /datasets/{dataset_id}/cases` | Paginated list with `status`, `priority`, `category`, `assigned_to_id`, `unassigned`, `include_archived`, `sort_by`, and `sort_order` filters. |
| `GET /datasets/{dataset_id}/cases/{case_id}` | Read case metadata and active association counts. |
| `PATCH /datasets/{dataset_id}/cases/{case_id}` | Update title, description, category, priority, or lifecycle status. |
| `DELETE /datasets/{dataset_id}/cases/{case_id}` | Archive and close a case without deleting evidence. |

Create example:

```http
POST /api/v1/datasets/{dataset_id}/cases
Authorization: Bearer <access-token>
Content-Type: application/json
```

```json
{
  "title": "Northbridge transfer review",
  "description": "Review linked rapid-transfer findings.",
  "category": "money_laundering",
  "priority": "high"
}
```

Successful responses include the case and counts, for example:

```json
{
  "id": "case-uuid",
  "dataset_id": "dataset-uuid",
  "title": "Northbridge transfer review",
  "category": "money_laundering",
  "priority": "high",
  "status": "open",
  "assigned_to_id": null,
  "account_count": 0,
  "finding_count": 0,
  "note_count": 0
}
```

Supported statuses are `open`, `in_review`, `resolved`, and `closed`. Invalid
transitions return `409`. Archived cases are excluded from lists unless
`include_archived=true`; their detail, timeline, and reports remain readable.
All paginated responses use `items`, `page`, `page_size`, `total`, and
`total_pages`, with page sizes capped at 100.

## Assignment

| Method and route | Purpose |
|---|---|
| `PATCH /datasets/{dataset_id}/cases/{case_id}/assignment` | Assign, reassign, or unassign an investigator. |
| `GET /datasets/{dataset_id}/cases/{case_id}/assignments` | Read the current assignee and paginated assignment history. |

Set `assigned_to_id` to an active investigator/admin UUID; send `null` to
remove an assignment. Assignment changes create audit events that retain the
previous and new assignee IDs, actor, and UTC timestamp. User emails are not
included in case responses or reports.

## Accounts and findings

| Method and route | Purpose |
|---|---|
| `GET /datasets/{dataset_id}/cases/{case_id}/accounts` | Page active linked accounts; use `include_removed=true` for retained links. |
| `POST /datasets/{dataset_id}/cases/{case_id}/accounts` | Link an account with optional case note. |
| `DELETE /datasets/{dataset_id}/cases/{case_id}/accounts/{account_id}` | Soft-unlink an account. |
| `GET /datasets/{dataset_id}/cases/{case_id}/findings` | Page active linked findings; use `include_removed=true` for retained links. |
| `POST /datasets/{dataset_id}/cases/{case_id}/findings` | Link a finding and snapshot its evidence references. |
| `DELETE /datasets/{dataset_id}/cases/{case_id}/findings/{finding_id}` | Soft-unlink a finding. |

An account link stores its safe account attributes at link time. A finding link
stores title, category, severity, lifecycle state, explanation, evidence,
parameters, associated account IDs, and bounded transaction snapshots. If a
link is removed and later restored, its previous snapshot remains under the
snapshot `history` array. The current source record and preserved snapshot are
both returned so a reviewer can distinguish later changes from link-time
evidence.

## Notes and timeline

| Method and route | Purpose |
|---|---|
| `GET /datasets/{dataset_id}/cases/{case_id}/notes` | Page notes; `include_archived=true` includes archived notes. |
| `POST /datasets/{dataset_id}/cases/{case_id}/notes` | Add a note. |
| `GET /datasets/{dataset_id}/cases/{case_id}/notes/{note_id}` | Read a note. |
| `PATCH /datasets/{dataset_id}/cases/{case_id}/notes/{note_id}` | Edit a note and append a content revision. |
| `DELETE /datasets/{dataset_id}/cases/{case_id}/notes/{note_id}` | Archive a note without deleting its history. |
| `GET /datasets/{dataset_id}/cases/{case_id}/notes/{note_id}/history` | Page immutable note versions. |
| `GET /datasets/{dataset_id}/cases/{case_id}/timeline` | Page chronological audit events. |

The initial note is revision 1. Every content edit appends a new revision with
the editor and UTC timestamp. Audit/timeline metadata contains note IDs and
revision numbers, never note contents. Timeline results are based on persisted
audit entries only.

## Reports and exports

| Method and route | Purpose |
|---|---|
| `GET /datasets/{dataset_id}/cases/{case_id}/reports/investigation.pdf` | Generate the case overview, accounts, findings, notes, evidence references, timeline, and report timestamp. |
| `GET /datasets/{dataset_id}/cases/{case_id}/exports/evidence.csv?limit=1000` | Export linked accounts, findings, and explicit transaction evidence references. |

PDF generation is limited to 250 records per report section. CSV exports accept
at most 5,000 rows and return `413` if the export would exceed the requested
limit. CSV cells are escaped by the standard CSV writer and formula-triggering
text is prefixed to prevent spreadsheet execution. Exports omit account
external IDs, user emails, and unrelated dataset records.
