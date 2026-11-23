# Background Analysis and Orchestration

Phase 11 runs dataset analysis in a Celery worker backed by the existing MuleTrace Redis service. PostgreSQL remains the source of truth for job state, stage progress, cancellation, retries, and results. Task messages contain only a job UUID; Celery uses JSON serialization, accepts only JSON, stores no task result, and never receives an ORM object, session, credentials, or analysis payload.

## API

All routes require a bearer token and the caller must own the dataset. Dataset and job IDs outside that scope return the same not-found response.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/datasets/{dataset_id}/analysis` | Submit a pipeline run; returns `202` |
| `GET` | `/api/v1/datasets/{dataset_id}/analysis` | List jobs with `page`, `page_size`, and optional `status` |
| `GET` | `/api/v1/datasets/{dataset_id}/analysis/{job_id}` | Read job status and safe results |
| `POST` | `/api/v1/datasets/{dataset_id}/analysis/{job_id}/cancel` | Cancel queued work or request cancellation at the next stage boundary |

Example submission:

```http
POST /api/v1/datasets/6b53f7f8-4bca-4baf-9fa7-497ab1e3525f/analysis
Authorization: Bearer <access-token>
Idempotency-Key: may-2026-investigation-01
Content-Type: application/json
```

```json
{
  "analysis_cutoff": "2026-05-31T23:59:59Z",
  "detection_enabled": true,
  "risk_scoring_enabled": true,
  "ml": {
    "enabled": true,
    "entity_types": ["ACCOUNT", "TRANSACTION"],
    "algorithms": ["isolation_forest"]
  }
}
```

The response includes the job UUID, `QUEUED` state, progress, current stage, retry count, and timestamps. It does not expose Celery task IDs, raw configuration, credentials, or internal exceptions. `Idempotency-Key` values must be 8–128 visible ASCII characters; only a SHA-256 digest is stored. Repeating a key for the same user and dataset returns the original job.

Example response:

```json
{
  "id": "59f4b9d0-ec45-4888-b364-831bf7303cae",
  "dataset_id": "6b53f7f8-4bca-4baf-9fa7-497ab1e3525f",
  "status": "QUEUED",
  "progress_percent": 0,
  "current_stage": "queued",
  "retry_count": 0,
  "cancel_requested": false,
  "result_summary": null,
  "error_summary": null,
  "created_at": "2026-06-01T09:00:00Z",
  "started_at": null,
  "finished_at": null
}
```

## Lifecycle and stages

The external states are `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, and `CANCELLED`; PostgreSQL retains the existing lowercase status convention. The pipeline persists each stage under its own key in the job's stage summary as it progresses: configuration, graph loading, rule detection and finding persistence, risk scoring, optional ML feature extraction/inference/finding persistence, final risk scoring, then completion. Each stage stores its start/end timestamps, duration, state, and safe counts. A failed stage leaves earlier committed findings and assessments intact and marks the job failed with a safe summary; it is never reported as completed. Disabled stages are recorded as skipped.

Each stage uses independent database transactions. Existing finding persistence is idempotent per analysis job, risk scoring is versioned per job, and model metadata uses a stable job-derived model version so a retry can accept an identical registry record. A PostgreSQL task-ID fence prevents an obsolete worker from claiming work after recovery. A cancellation request does not kill an active process; the pipeline observes it at stage boundaries and marks the job cancelled while retaining completed stage outputs.

The default concurrency policy permits one active analysis for a dataset and three active analyses per user. Configure the limits with `ANALYSIS_MAX_ACTIVE_PER_DATASET` and `ANALYSIS_MAX_ACTIVE_PER_USER`; PostgreSQL row locks serialize submissions against those limits. Synchronous synthetic generation and CSV import endpoints remain unchanged in this phase.

Transient database connection failures retry up to `ANALYSIS_MAX_RETRIES` with bounded exponential backoff. A periodic maintenance task checks stale heartbeats and requeues work with a new Celery task ID; exhausted jobs fail safely. Celery Beat must run for periodic recovery. Workers use late acknowledgements, reject work after worker loss, prefetch one job, and use configured soft/hard timeouts. Ensure the worker timeout remains lower than the stale-job interval.

## Worker and configuration

The root `.env` or `backend/.env` may configure `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD`, and optionally `CELERY_BROKER_URL`. Explicit broker URLs are secrets and must be URL-encoded when they contain special characters. `ANALYSIS_MAX_ACTIVE_PER_DATASET`, `ANALYSIS_MAX_ACTIVE_PER_USER`, `ANALYSIS_MAX_RETRIES`, `ANALYSIS_TASK_SOFT_TIME_LIMIT`, `ANALYSIS_TASK_TIME_LIMIT`, `ANALYSIS_STALE_JOB_SECONDS`, and `ANALYSIS_BROKER_CONNECT_TIMEOUT` set operational bounds.

Start the API, worker, and Beat scheduler in separate terminals from `backend/`:

```powershell
python run.py
celery -A app.tasks.celery_app:celery_app worker --pool=solo --queues=muletrace.analysis,muletrace.maintenance --loglevel=INFO
celery -A app.tasks.celery_app:celery_app beat --loglevel=INFO
```

Use `--pool=solo` on Windows. The worker and Beat scheduler use the existing `muletrace` Redis infrastructure and do not require another container or application image. On shutdown, press Ctrl+C in each worker and Beat terminal and wait for the normal shutdown message. Do not run `celery purge` against shared infrastructure.

Worker health and queue monitoring:

```powershell
python -m app.tasks.worker_health
celery -A app.tasks.celery_app:celery_app inspect active_queues
celery -A app.tasks.celery_app:celery_app inspect active
celery -A app.tasks.celery_app:celery_app inspect reserved
```

The health command issues a bounded Celery ping and returns only healthy/unavailable. `active` and `reserved` show task identifiers; use job IDs from the API to correlate work. If Redis is unavailable, API submission returns `503` and the new job is marked `FAILED`, never left falsely reported as queued. If the worker is unavailable, queued jobs remain in PostgreSQL and worker startup triggers recovery; Beat runs periodic stale-job recovery. Check API/worker logs and container health first. Never print broker URLs or task payloads containing analysis configuration.

## Troubleshooting

- **Submission returns `503`:** verify `muletrace-redis` is healthy, the Redis password matches the local environment, and the broker host/port are reachable from the API process.
- **Jobs remain `QUEUED`:** verify the worker is listening on both `muletrace.analysis` and `muletrace.maintenance`; run `worker_health` and inspect `active_queues`.
- **Jobs remain `RUNNING`:** verify Celery Beat is running and the worker can reach PostgreSQL. The stale recovery interval is `ANALYSIS_STALE_JOB_SECONDS`; recovery fences an old task ID before enqueueing a replacement.
- **A job is `FAILED`:** read only the API's safe `error_summary` and stage summary. Use protected operator logs to correlate by job ID and stage; do not expose transaction data, credentials, or raw exception details to API users.
- **Worker shutdown waits:** allow the current CPU-bound stage to reach its soft/hard time limit or finish, then verify the normal worker shutdown message. Cancellation requests do not forcibly interrupt a running algorithm.

The migration `c7e4a91d2f60` adds lifecycle fields, idempotency and task-ID uniqueness, range checks, and a stale-job index to `analysis_jobs`. It is additive and retains previous database records.

## ML and limitations

Phase 10 keeps fitted estimators in process memory and deliberately does not serialize them. This pipeline fits each selected model inside the worker task that uses it and persists only safe model metadata. It does not implement training queues, long-lived artifact storage, CSV import orchestration, distributed locks beyond PostgreSQL fencing, or frontend progress views. Model fitting can be repeated after a worker crash; model metadata and findings are designed to tolerate identical retries, but large jobs still need operational sizing and monitoring.
