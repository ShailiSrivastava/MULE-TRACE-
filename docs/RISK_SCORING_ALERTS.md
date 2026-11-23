# Risk Scoring and Finding Management

Phase 9 persists Phase 8 detector findings as evidence-backed investigative records, calculates explainable risk assessments, and provides owner-scoped lifecycle and risk APIs. Detection remains deterministic and separate from scoring.

## Finding data model

The additive Alembic revision `d41f6f8b9c20` adds:

- `detection_findings`: one canonical finding per dataset and stable deduplication key, with detector/version, category, severity, explanation, current status, event window, parameters, evidence, and first/last detected timestamps.
- `finding_accounts`: dataset-safe links from a finding to all participating accounts.
- `finding_transactions`: dataset-safe links from a finding to all supporting transactions. Transaction rows remain the source of transaction details; the finding stores references and evidence rather than copying transactions.
- `finding_observations`: an immutable per-analysis snapshot of parameters and evidence, uniquely keyed by dataset, finding, and analysis job.
- `finding_status_history`: append-only lifecycle changes with actor, reason, and timestamp.

Composite foreign keys prevent findings from pointing to accounts, transactions, or analysis jobs in another dataset. Account and transaction deletion is restricted while a finding refers to them. Deleting a finding removes its joins, observations, history, and finding-level risk assessments. Existing `DetectionAlert` rows and their one-transaction semantics are unchanged.

### Deduplication and reprocessing

Phase 8's deterministic deduplication key is unique within a dataset. Repeating the same finding in the same analysis job is idempotent: it creates no duplicate observation, status history, or audit event and does not move `last_detected_at`. A later analysis job with the same key adds an observation and updates the canonical finding's current detector output and last-detected timestamp without resetting status or assignment. Findings absent from a later run are retained; their previous evidence and lifecycle state are not erased.

The canonical finding ID must match the stable ID emitted by Phase 8. Conflicting IDs, changed account/transaction associations for an existing key, or references outside the dataset fail and roll back the complete persistence transaction.

## Risk scoring

`app/risk/` contains a deterministic scoring engine separate from the detectors. The configuration is passed to internal scoring callers as a validated `RiskScoringConfig`; detector weights, category weights, severity contributions, score version, and band boundaries can be changed without changing detection logic. Category weights default to `1.00` when a category has no explicit override.

For each distinct finding:

```text
finding_signal = detector_weight × category_weight × severity_contribution
```

For each account affected by one or more findings in the analysis:

```text
account_score = 1 − product(1 − finding_signal)
```

Repeated findings with the same deduplication key count once. Results are clamped by validated weights and normalized to six decimal places. Each score stores its model version and the component weights used. Account aggregation uses findings from that analysis; it does not add transaction amounts.

Illustrative defaults:

| Detector | Weight |
|---|---:|
| `rapid_transfers` | 0.90 |
| `fan_in` | 0.75 |
| `fan_out` | 0.75 |
| `circular_movement` | 0.95 |
| `multi_hop` | 0.65 |
| `unusual_activity` | 0.65 |
| `structuring` | 0.70 |

| Severity | Contribution |
|---|---:|
| `info` | 0.05 |
| `low` | 0.20 |
| `medium` | 0.40 |
| `high` | 0.70 |
| `critical` | 0.90 |

The default illustrative bands are `low` for `[0, 0.25)`, `medium` for `[0.25, 0.50)`, `high` for `[0.50, 0.75)`, and `critical` for `[0.75, 1]`. These boundaries are configurable and are not regulatory standards. Scores are prioritization signals, not probabilities of criminal activity. Account identity and personal characteristics are not scoring inputs. Finding evidence preserves the detector's currency-specific evidence; the scoring engine does not aggregate across currencies.

`risk_assessments` now supports exactly one scope, either an account or a finding. The migration preserves prior account scores, labeling their scoring version `legacy` and initializing their component snapshots to `{}`. New rows are unique per analysis job, subject, and scoring version, so a changed configuration retains earlier assessments. A scoring version is immutable for a given analysis: a caller that supplies different weights under an already-used version receives a conflict and must use a new version label.

## Lifecycle and authorization

The persisted lifecycle is:

| Current status | Allowed next status |
|---|---|
| `NEW` | `REVIEWING`, `DISMISSED` |
| `REVIEWING` | `RESOLVED`, `DISMISSED` |
| `RESOLVED` | `REVIEWING` |
| `DISMISSED` | none |

Resolving or dismissing requires a nonblank reason. Every actual transition creates a history row and audit event. Repeating the current status is an idempotent no-op. Assignment can be changed or cleared; a target must be an active `INVESTIGATOR`. Finding routes never accept role updates.

All routes require an active authenticated user and dataset ownership. Status and assignment changes additionally require the existing `ADMIN` or `INVESTIGATOR` role. Analysts can read their owned datasets but cannot change lifecycle status or assignments. The current data model has no shared-dataset membership, so role alone does not grant access to another user's dataset.

## API contracts

All endpoints are under `/api/v1` and require a bearer token.

| Method and path | Behavior |
|---|---|
| `GET /datasets/{dataset_id}/findings` | Paginated finding list. Filters: `category`, `severity`, `risk_level`, `status`, `assigned_to_id`, `unassigned`, `start_at`, `end_at`. Date filters apply to `last_detected_at` and require timezone offsets. Sort fields: `created_at`, `first_detected_at`, `last_detected_at`, `severity`, `status`; sort order is `asc` or `desc`. |
| `GET /datasets/{dataset_id}/findings/{finding_id}` | Finding fields, evidence, detector parameters, account and transaction references, observations, status history, and latest finding score. |
| `PATCH /datasets/{dataset_id}/findings/{finding_id}/status` | Change lifecycle status. |
| `PATCH /datasets/{dataset_id}/findings/{finding_id}/assignment` | Assign or clear an investigator. |
| `GET /datasets/{dataset_id}/risk-summary` | Finding totals and category/severity/status/risk-band counts, distinct affected accounts and transactions, and latest observation time. |
| `GET /datasets/{dataset_id}/accounts/{account_id}/risk` | Latest account assessment and distinct finding count. |

Example status update:

```http
PATCH /api/v1/datasets/9ab0d975-40d9-4f7e-9707-b389fe762801/findings/66071ce0-075d-4d09-9f1e-f884199222df/status
Authorization: Bearer <access-token>
Content-Type: application/json
```

```json
{
  "status": "RESOLVED",
  "reason": "Reviewed the evidence and completed the investigation."
}
```

Example paginated list response:

```json
{
  "items": [
    {
      "id": "66071ce0-075d-4d09-9f1e-f884199222df",
      "dataset_id": "9ab0d975-40d9-4f7e-9707-b389fe762801",
      "detector_name": "rapid_transfers",
      "detector_version": "1.0",
      "category": "rapid_transfer_chain",
      "severity": "high",
      "title": "Rapid transfer sequence",
      "explanation": "Several transfers occurred in a short window.",
      "deduplication_key": "<64-character-sha256>",
      "status": "NEW",
      "assigned_to_id": null,
      "first_detected_at": "2026-11-01T12:00:00Z",
      "last_detected_at": "2026-11-01T12:00:00Z",
      "event_window_start": "2026-11-01T11:59:30Z",
      "event_window_end": "2026-11-01T12:00:00Z",
      "account_count": 2,
      "transaction_count": 3,
      "risk_score": "0.630000",
      "risk_level": "high",
      "scoring_model_version": "1.0",
      "created_at": "2026-11-01T12:00:00Z",
      "updated_at": "2026-11-01T12:00:00Z"
    }
  ],
  "page": 1,
  "page_size": 25,
  "total": 1,
  "total_pages": 1
}
```

List query parameters are validated; unsupported sorting or malformed timestamps return 422. Unowned datasets and findings return 404. Missing authentication returns 401, insufficient role returns 403, invalid lifecycle transitions return 409, and database failures use the shared safe service-error response.

Example assignment request:

```http
PATCH /api/v1/datasets/9ab0d975-40d9-4f7e-9707-b389fe762801/findings/66071ce0-075d-4d09-9f1e-f884199222df/assignment
Authorization: Bearer <access-token>
Content-Type: application/json
```

```json
{
  "assigned_to_id": "ae03a3d1-2c73-4a0a-9a30-03dcafc93e47"
}
```

Example risk summary response:

```json
{
  "dataset_id": "9ab0d975-40d9-4f7e-9707-b389fe762801",
  "total_findings": 1,
  "findings_by_category": {"rapid_transfer_chain": 1},
  "findings_by_severity": {"info": 0, "low": 0, "medium": 0, "high": 1, "critical": 0},
  "findings_by_status": {"NEW": 1, "REVIEWING": 0, "RESOLVED": 0, "DISMISSED": 0},
  "findings_by_risk_level": {"low": 0, "medium": 0, "high": 1, "critical": 0, "unscored": 0},
  "affected_account_count": 2,
  "affected_transaction_count": 3,
  "latest_analysis_at": "2026-11-01T12:00:00Z"
}
```

An account risk response includes the latest account assessment and the number of distinct findings contributing to its score:

```json
{
  "dataset_id": "9ab0d975-40d9-4f7e-9707-b389fe762801",
  "account_id": "21ac4a70-a12e-4e63-8c34-a048b796ced3",
  "risk": {
    "score": "0.630000",
    "risk_level": "high",
    "scoring_model_version": "1.0",
    "score_components": {"findings": [{"deduplication_key": "<sha256>", "detector_name": "rapid_transfers", "category": "rapid_transfer_chain", "severity": "high", "detector_weight": "0.90", "category_weight": "1.00", "severity_contribution": "0.70", "finding_signal": "0.630000"}]},
    "assessed_at": "2026-11-01T12:01:00Z",
    "analysis_job_id": "a3108ed5-25f0-49a6-8f60-6640d837106e"
  },
  "distinct_finding_count": 1
}
```

## Audit behavior

The append-oriented `audit_logs` table records finding creation, subsequent observation, risk calculation, status changes, assignment, and unassignment. Events retain actor, dataset, entity, request correlation ID where available, and small safe metadata such as detector/category/severity, status transition, scoring version, or affected-row counts. Evidence, transaction amounts, passwords, and tokens are not copied into audit details. The status-history table retains transition reasons separately.

## Known limitations

- Risk scoring is invoked by an internal service with a completed analysis job; Phase 9 does not expose an endpoint to launch detection or scoring.
- No worker queue or automatic schedule is included. Callers must orchestrate Phase 8 detection, persistence, then scoring.
- Findings are not automatically resolved or deleted when a later run omits them. Investigators control their lifecycle.
- Dataset access is owner-only because shared-dataset membership is not part of the current schema.
- Default weights and bands are illustrative and require operational review before production use.
- Risk assessments are deterministic prioritization values, not calibrated likelihoods or regulatory decisions.
