# MuleTrace Production Operations

This guide covers the backend-only production deployment profile. It does not
change or reuse the development Compose services or their persistent volumes.

## Production Compose resources

| Resource | Name | Ports / storage |
| --- | --- | --- |
| API image | `muletrace/backend:<release-tag>` | Built from `backend/Dockerfile` in this repository |
| PostgreSQL image / container | `postgres:16.16-alpine3.24` / `muletrace-prod-postgres` | No host port; `muletrace_prod_postgres_data` |
| Redis image / container | `redis:7.4.12-alpine3.22` / `muletrace-prod-redis` | No host port; `muletrace_prod_redis_data` |
| API container | `muletrace-prod-api` | `127.0.0.1:8000:8000` by default; place a TLS reverse proxy in front |
| Celery worker / Beat | `muletrace-prod-worker`, `muletrace-prod-beat` | Internal network only |
| Compose network | `muletrace_prod_network` | Internal bridge network |
| Compose project | `muletrace` | Separate service, container and volume names from development |

The development stack retains `muletrace-postgres`, `muletrace-redis`,
`muletrace_network`, `mule-trace_postgres_data`, and `mule-trace_redis_data`.
The production profile never mounts those development volumes. Normal image
rebuilds do not remove either production data volume. Never use `down -v` for a
routine deployment.

## Prepare configuration and secrets

Copy `.env.production.example` to the ignored `.env.production`, replace every
example hostname and choose a unique release tag. Create four owner-readable
secret files at the configured paths: `postgres_password`, `redis_password`,
`jwt_secret_key`, and `metrics_token`. Use independently generated values;
the two service passwords must each have at least 24 varied characters, the
JWT secret at least 48, and the metrics token at least 32. Restrict access to
the files and keep them out of source control and backups that are not
encrypted. Compose file secrets are mounted read-only into the relevant
containers; they are not an encrypted secret store, so protect the host and
backup the secret files separately.

Set `TRUSTED_HOSTS` to the API host names and `CORS_ORIGINS` to explicit HTTPS
frontend origins. If a reverse proxy supplies forwarded headers, enable
`PROXY_HEADERS_ENABLED` and list only that proxy's exact IP addresses in
`FORWARDED_ALLOW_IPS`. The API binds to loopback by default; configure the
proxy to reach that address. PostgreSQL and Redis have no published host
ports. `DATABASE_SSLMODE=disable` is only for the private Compose network; use
TLS and certificate verification for an externally managed database.

## Build, migrate, deploy

From the repository root, validate configuration and build an image from the
checked-out source (the release tag must be immutable):

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.production -f docker-compose.prod.yml build --no-cache api-prod worker-prod beat-prod migrate-prod
```

Start only the database and Redis services first, and verify both health
states. On a new production deployment this creates only the separate
`muletrace_prod_*` volumes. Existing deployments retain their data:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml up -d postgres-prod redis-prod
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Apply the Alembic chain as an explicit release step, then start the API,
worker, and scheduler:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml --profile migrations run --rm migrate-prod
docker compose --env-file .env.production -f docker-compose.prod.yml up -d api-prod worker-prod beat-prod
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

Readiness checks PostgreSQL and Redis. The worker container health check uses
Celery's ping control command. Check container health and logs without
printing environment variables or secret files:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 api-prod worker-prod beat-prod
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

The internal metrics endpoint is disabled unless configured and always
requires `X-Metrics-Token`. Keep it behind a private monitoring path; do not
publish it through an unauthenticated public route. Metrics are process-local,
so scrape each API replica separately.

For a rollback, deploy the previous immutable application image only when its
schema remains compatible. Migrations are additive, but application rollback
compatibility still needs release-specific review. Do not run a downgrade as
an automatic rollback.

## PostgreSQL backup and recovery

Take regular encrypted backups outside the database volume and copy them to a
separate failure domain. The following commands read the mounted password
inside the database container, do not put it in the shell command text, and
write a custom-format archive to the operator's protected backup directory:

```sh
umask 077
backup_file="muletrace-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres-prod sh -c 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom --no-owner --no-privileges' > "$backup_file"
```

Check that the archive is nonempty, encrypt it using the organization's
approved backup key, transfer it off-host, and record its checksum and
retention date. Do not store backups inside a Docker volume on the same host.
Schedule and document restore drills; a successful dump alone does not prove
recoverability.

Restore-test to a separate empty test database or isolated PostgreSQL instance,
never over the live production database. For example, with the production
Compose PostgreSQL container and a pre-created `muletrace_restore_test`
database:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml exec -T postgres-prod sh -c 'export PGPASSWORD="$(cat /run/secrets/postgres_password)"; exec pg_restore --username "$POSTGRES_USER" --dbname muletrace_restore_test --no-owner --no-privileges --exit-on-error' < "$backup_file"
```

Validate the restored schema and representative row counts, then remove the
test database only through the normal database change procedure after the
restore drill has been recorded. Keep the original archive unchanged.

## Monitoring and response

- Alert on failed liveness/readiness checks, repeated API 5xx/429 responses,
  database connection pool exhaustion, slow-query counts, Redis failures,
  Celery worker health, and analysis jobs stuck beyond the configured timeout.
- Logs are JSON and include request IDs. They intentionally omit exception
  messages, SQL text, bind values, authentication data, and request bodies.
- The optional error-monitor hook receives only request ID, exception type,
  method, route template, and status. Register an approved integration in the
  process; do not send financial payloads or secrets to it.
- Tune pool size and worker concurrency against the database's connection
  limit. The API pool is per process; Celery workers also open database
  connections. Keep their combined maximum below the database budget.
- Redis is used for Celery and production rate limits. A Redis failure causes
  protected writes to fail closed with a generic 503; restore Redis health
  before retrying requests.

## Development and test commands

Development Compose remains separate and unchanged. From `backend/`, run
`pytest -q`, `ruff check .`,
`python -m compileall -q app alembic run.py tests`, `alembic upgrade head`,
and `alembic check`. CI runs the backend checks, dependency audit, frontend
test/build, migration checks, and a fresh Docker image build on pull requests.
