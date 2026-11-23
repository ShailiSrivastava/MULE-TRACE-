# MuleTrace Windows Setup Guide

A beginner-friendly, step-by-step setup guide for Windows users.

---

## 1. Prerequisites Checklist

Ensure the following tools are installed on your Windows machine:

1. **Git for Windows**:
   - Verify in PowerShell:
     ```powershell
     git --version
     ```
2. **Node.js (v18 or higher recommended)**:
   - Verify in PowerShell:
     ```powershell
     node -v
     npm -v
     ```
3. **Python (3.12 or newer)**:
   - Verify in PowerShell:
     ```powershell
     python --version
     ```
4. **Docker Desktop with Compose**:
   - Verify with `docker compose version`.
   - Start Docker Desktop and confirm `docker info` can reach the engine.

---

## 2. Local Infrastructure (PostgreSQL and Redis)

From the repository root, create the ignored local environment file and populate unique local values for the PostgreSQL and Redis credentials. The example intentionally leaves secrets blank.

```powershell
Copy-Item .env.example .env
docker volume create mule-trace_postgres_data
docker volume create mule-trace_redis_data
docker compose up -d postgres redis
docker compose ps
```

Compose uses project name `muletrace`, containers `muletrace-postgres` and `muletrace-redis`, network `muletrace_network`, and host ports `127.0.0.1:5432` and `127.0.0.1:6379`. It attaches the existing persistent volumes `mule-trace_postgres_data` and `mule-trace_redis_data` to preserve Phase 2 data. `docker compose down` preserves those volumes; do not use `docker compose down -v` unless you intend to remove the stored data.

For future application images, rebuild from the current MuleTrace Dockerfile with `docker compose build --no-cache <service>` before startup. Do not reuse another project's application image or assume an older image contains current source.

---

## 3. Backend Setup (FastAPI & Python)

Production deployment, secret-file configuration, image builds, and safe PostgreSQL backup/restore procedures are documented in [Production Operations](OPERATIONS.md). Do not use the development `.env` or development database volumes for a production deployment.

Open PowerShell at the repository root, then enter the backend directory:

```powershell
cd backend
python --version
```
Use Python 3.12 or newer for the backend.

### Step 2.1: Create a Python Virtual Environment
```powershell
python -m venv .venv
```

### Step 2.2: Enable PowerShell Script Execution & Activate
On Windows, PowerShell may block script execution by default. Allow the current process to activate the environment:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```
*(Your prompt should now display `(.venv)`)*

### Step 2.3: Install Backend Dependencies
```powershell
pip install -r requirements.txt
```

### Step 2.4: Run Backend Tests
Verify the installation by running the test suite:
```powershell
pytest
```

### Step 2.5: Apply Database Migrations
```powershell
alembic upgrade head
```
This applies the additive schema revisions through the current `e7f192c4a60d` head, including analysis-job lifecycle and case-history fields. Existing user, dataset, analysis, and case records are preserved.

### Step 2.6: Start the Backend Server
```powershell
python run.py
```
- API Root: `http://127.0.0.1:8000/`
- Liveness: `http://127.0.0.1:8000/health/live`
- Readiness: `http://127.0.0.1:8000/health/ready` (requires PostgreSQL and Redis)
- Versioned API Root: `http://127.0.0.1:8000/api/v1`
- Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

The backend loads process environment variables first, then the project-root `.env`, then `backend/.env`. Leave `DATABASE_URL` blank to have it built from the PostgreSQL settings. `/health` remains as a compatibility liveness endpoint. Database credentials are not hardcoded and must be supplied through the ignored environment file.

If port 8000 is occupied by an older or unrelated server, inspect its owning process and routes before acting; do not stop an unidentified process. For an isolated local check, set `$env:API_PORT = '8787'` in that PowerShell session before running `python run.py`.

Before logging in, set `JWT_SECRET_KEY` in the ignored `.env` to a randomly generated secret. For example, from `backend/` run `python -c "import secrets; print(secrets.token_urlsafe(48))"` and copy its output into `.env`. Use a distinct secret in every environment. The API rejects missing or shorter than 32-character keys.

Authentication endpoints are available under `/api/v1/auth`: `POST /register`, `POST /login`, and protected `GET /me`. Registration creates an active `ANALYST` account. The token is a 30-minute bearer token by default. To provision the first administrator, register the intended account, note its user UUID from the registration response, then run from `backend/`:

```powershell
python -m app.cli bootstrap-admin --user-id <user-uuid>
```

After that, administrators can manage roles and activation with the protected `/api/v1/admin/users/{user_id}/role` and `/api/v1/admin/users/{user_id}/activation` routes. Inactive users cannot log in or use existing tokens.

For account and transaction routes, pagination, filters, and example payloads, see [Accounts and Transactions API](ACCOUNTS_TRANSACTIONS_API.md). Those routes require an already-existing dataset owned by the authenticated user.

For asynchronous graph, detection, risk, and optional ML orchestration, start the worker and periodic recovery scheduler from `backend/` in separate terminals:

```powershell
celery -A app.tasks.celery_app:celery_app worker --pool=solo --queues=muletrace.analysis,muletrace.maintenance --loglevel=INFO
celery -A app.tasks.celery_app:celery_app beat --loglevel=INFO
```

Configure Redis using the environment settings in `.env.example`. Read the [Background Processing guide](BACKGROUND_PROCESSING.md) for API examples, worker health, queue inspection, lifecycle, retry, cancellation, recovery, and troubleshooting.

Dataset creation, seeded synthetic data, CSV upload routes, canonical headers, and import limits are described in [Dataset Management and CSV Imports](DATASETS_SYNTHETIC_CSV.md). The default CSV caps are 10 MiB and 10,000 rows.

The reusable, non-API transaction graph engine, metric definitions, filters, and traversal limits are described in [Financial Transaction Graph Engine](GRAPH_ENGINE.md).

---

## 4. Frontend Setup (React, Vite, TypeScript)

Open a **separate** PowerShell terminal window at the repository root:

```powershell
cd frontend
```

### Step 3.1: Copy Frontend Environment Variables
```powershell
Copy-Item .env.example .env
```

### Step 3.2: Install NPM Dependencies
```powershell
npm install
```

### Step 3.3: Run Frontend Tests
Verify the frontend foundation with Vitest:
```powershell
npm test
```

### Step 3.4: Start the Frontend Development Server
```powershell
npm run dev
```
Open your browser and navigate to:
`http://localhost:5173`

---

## 5. API Testing with Postman

1. Open Postman.
2. Click **Import** in the top left.
3. Select `postman/MuleTrace_API.postman_collection.json`.
4. Select `postman/MuleTrace_Local.postman_environment.json`.
5. In Postman, switch the active environment to **MuleTrace Local Environment**.
6. Run the **Get Root Info** and **Health Check** requests to confirm API readiness.
