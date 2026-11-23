# MuleTrace

**MuleTrace** is a full-stack trace analysis and graph visualization platform. This repository provides a clean, modular foundation architected for decoupled frontend and backend development.

---

## Team & Collaboration


- **Repository**: [https://github.com/ShailiSrivastava/MULE-TRACE-](https://github.com/ShailiSrivastava/MULE-TRACE-)
- **Default Branch**: `main`

---

## Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Frontend** | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, Cytoscape.js, Recharts |
| **Backend** | Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL, Redis (local infrastructure) |
| **Testing** | Vitest, React Testing Library, Pytest, HTTPX |
| **API Testing** | Postman (Collection & Environment included) |

---

## Directory Structure

```text
MULE-TRACE/
├── .env.example              # Root environment template
├── .gitignore                # Comprehensive Git exclusions for Python, Node, & secrets
├── docker-compose.yml        # Local PostgreSQL and Redis services with named volumes
├── README.md                 # Project documentation and start guide
│
├── docs/                     # Architectural & team workflow documentation
│   ├── ARCHITECTURE.md       # High-level architecture & design
│   ├── RISK_SCORING_ALERTS.md # Phase 9 finding lifecycle and scoring APIs
│   ├── MACHINE_LEARNING.md   # Phase 10 anomaly analysis and limitations
│   ├── BACKGROUND_PROCESSING.md # Phase 11 job APIs, worker setup, and lifecycle
│   ├── CONTRIBUTING.md       # Git branching & collaboration guide
│   └── SETUP_GUIDE.md        # Comprehensive Windows setup walkthrough
│
├── backend/                  # FastAPI + SQLAlchemy backend
│   ├── .env.example          # Backend environment variable template
│   ├── alembic.ini           # Migration configuration (no credentials)
│   ├── pyproject.toml        # Python requirement and pytest configuration
│   ├── requirements.txt      # Python dependencies
│   ├── run.py                # Configured Uvicorn entrypoint
│   ├── alembic/              # Migration environment and revisions
│   │   └── versions/
│   │       ├── 0001_empty_baseline.py
│   │       └── ...            # Additive revisions through Phase 11
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI app factory and middleware registration
│   │   ├── api/              # Health and versioned API routers
│   │   ├── ml/               # Feature engineering, estimators, evaluation, registry
│   │   ├── models/           # Typed SQLAlchemy relational mappings
│   │   └── core/
│   │       ├── __init__.py
│   │       ├── config.py     # Pydantic Settings configuration
│   │       ├── database.py   # SQLAlchemy engine & request-scoped sessions
│   │       ├── model_base.py # Shared declarative base and UTC timestamp type
│   │       ├── errors.py     # Consistent API error responses
│   │       └── observability.py # Structured request logs and correlation
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py       # Pytest fixtures and TestClient
│       ├── test_health.py    # Health check & root API tests
│       ├── test_database.py  # Session, connectivity, and migration tests
│       └── test_models.py    # ORM relations, constraints, and deletion tests
│
├── frontend/                 # Vite + React + TypeScript frontend
│   ├── .env.example          # Frontend environment variable template
│   ├── components.json       # shadcn/ui configuration
│   ├── index.html            # Vite HTML entry
│   ├── package.json          # Node dependencies & scripts
│   ├── postcss.config.js     # PostCSS configuration
│   ├── tailwind.config.js    # Tailwind CSS design system configuration
│   ├── tsconfig.json         # TypeScript compiler options & aliases (@/*)
│   ├── tsconfig.node.json    # TypeScript Node configuration
│   ├── vite.config.ts        # Vite & Vitest configuration
│   └── src/
│       ├── App.tsx           # Foundation dashboard component
│       ├── index.css         # Tailwind & shadcn CSS variables
│       ├── main.tsx          # React application root
│       ├── vite-env.d.ts     # Vite environment types
│       ├── components/
│       │   └── ui/           # Destination for shadcn/ui components
│       ├── lib/
│       │   └── utils.ts      # Tailwind class utility (cn helper)
│       └── test/
│           ├── App.test.tsx  # React Testing Library unit tests
│           └── setup.ts      # Vitest test setup
│
└── postman/                  # Postman collections & environments
    ├── MuleTrace_API.postman_collection.json
    └── MuleTrace_Local.postman_environment.json
```

---

## Getting Started on Windows (PowerShell)

Follow these steps to run the frontend and backend separately.

### Prerequisites
Make sure you have installed:
1. **Node.js** (v18+) and **npm**: Verify with `node -v` and `npm -v`.
2. **Python** (3.12+): Verify with `python --version`.
3. **Git**: Verify with `git --version`.
4. **Docker Desktop** with Docker Compose: Verify with `docker compose version` and ensure the engine is running.

---

### 1. Starting Local Infrastructure

From the repository root, create a local environment file and set unique values for `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `REDIS_PASSWORD`. Then start the services:

```powershell
Copy-Item .env.example .env
docker volume create mule-trace_postgres_data
docker volume create mule-trace_redis_data
docker compose up -d postgres redis
docker compose ps
```

The checked-in template leaves secrets blank. The Compose project is named `muletrace`; PostgreSQL and password-protected Redis bind to localhost and use project-specific containers, a network, and persistent volumes. `docker compose down` stops the containers while preserving their data; do not use `docker compose down -v` unless you intend to delete it.

| Service | Container | Host port | Persistent volume |
|---|---|---:|---|
| PostgreSQL | `muletrace-postgres` | `127.0.0.1:5432` | `mule-trace_postgres_data` |
| Redis | `muletrace-redis` | `127.0.0.1:6379` | `mule-trace_redis_data` |

Both containers attach to `muletrace_network`. The volume names retain the Phase 2 data while the Compose project and containers adopt the `muletrace` namespace.

---

### 2. Setting Up and Running the Backend

Open **PowerShell Terminal 1**:

```powershell
# Navigate into backend directory
cd backend

# Confirm Python 3.12 or newer
python --version

# Create a virtual environment
python -m venv .venv

# Enable script execution for this session and activate
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# Install backend dependencies
pip install -r requirements.txt

# Run backend unit tests
pytest

# Apply database migrations
alembic upgrade head

# Start the FastAPI server
python run.py
```

- **API Root**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Liveness Check**: [http://127.0.0.1:8000/health/live](http://127.0.0.1:8000/health/live)
- **Readiness Check**: [http://127.0.0.1:8000/health/ready](http://127.0.0.1:8000/health/ready) (requires PostgreSQL)
- **Versioned API Root**: [http://127.0.0.1:8000/api/v1](http://127.0.0.1:8000/api/v1)
- **Interactive Swagger Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

### 2. Setting Up and Running the Frontend

Open **PowerShell Terminal 2**:

```powershell
# Navigate into frontend directory
cd frontend

# Create your local environment file
Copy-Item .env.example .env

# Install dependencies
npm install

# Run frontend unit tests
npm test

# Start the Vite development server
npm run dev
```

- **Frontend App**: [http://localhost:5173/](http://localhost:5173/)

---

### 3. API Testing with Postman

1. Open **Postman**.
2. Click **Import** and select:
   - `postman/MuleTrace_API.postman_collection.json`
   - `postman/MuleTrace_Local.postman_environment.json`
3. Set the active environment to **MuleTrace Local Environment**.
4. Execute the requests to verify that the FastAPI backend is running and healthy.

---

## Adding shadcn/ui Components

The frontend is pre-configured with `components.json` and `src/lib/utils.ts`. To add shadcn/ui components in the future, navigate to `frontend/` and run:

```powershell
npx shadcn@latest add button card
```

---

## Backend Configuration

The backend reads environment variables from the process first, then the project-root `.env`, then `backend/.env` (which takes precedence over the root file). `DATABASE_URL` is optional; when blank or omitted, the backend builds the SQLAlchemy URL from `POSTGRES_*` values. Credentials have no code defaults; configure them in an ignored `.env` before running database operations.

For future application containers, build a fresh project-specific image from the current repository Dockerfile with `docker compose build --no-cache <service>` before startup. Do not rely on an image built from another project or an older MuleTrace source revision.

`/health` remains available for compatibility and reports process liveness. `/health/live` is the explicit liveness endpoint. `/health/ready` checks PostgreSQL and returns HTTP 503 while the database is unavailable.

## Database Schema

The initial relational schema is managed by Alembic revision `19b6f8790061` and includes users, datasets, accounts, transactions, analysis jobs, detection alerts, risk assessments, investigation cases, case membership tables, and audit logs. Synthetic and curated transaction labels are stored separately in `ground_truth_labels`, apart from algorithm-produced findings. Transactions preserve amount, currency, event time, channel, status, and source metadata; repeated transfers between the same account pair are allowed. Later revisions add authentication, transaction filter indexes, CSV import tracking, Phase 9 persisted findings and versioned risk assessments, and Phase 10 model registry metadata (`b18f3a9d2c74`).

Apply the baseline and schema with `alembic upgrade head` from `backend/`. Authentication fields are added by revision `899fa61457b5`; the migration keeps existing users and assigns them the least-privileged `ANALYST` role. Existing users with no password hash cannot log in until an operator arranges a password reset through the deployment's approved process.

## Authentication API

The backend provides versioned endpoints at `/api/v1/auth/register`, `/api/v1/auth/login`, and `/api/v1/auth/me`. Public registration creates an active `ANALYST` account; role selection is never accepted during registration. Login returns a short-lived bearer access token (30 minutes by default), and protected routes re-read the user from PostgreSQL on each request so deactivation and role changes take effect immediately. Passwords are hashed with Argon2id and never returned from the API. `ADMIN` users can manage account activation and roles at `/api/v1/admin/users/{user_id}/activation` and `/api/v1/admin/users/{user_id}/role`.

Set a unique `JWT_SECRET_KEY` in the ignored local `.env` or deployment environment. Generate it with `python -c "import secrets; print(secrets.token_urlsafe(48))"`; the API rejects missing or shorter than 32-character keys. Keep the issuer, audience, and access-token expiry settings environment-configurable. To establish the first administrator, register the intended account and run `python -m app.cli bootstrap-admin --user-id <user-uuid>` from `backend/`. This one-time operator command only succeeds when no active administrator exists; subsequent role changes require an authenticated administrator.

## Accounts and Transactions API

Authenticated account and transaction endpoints are scoped under `/api/v1/datasets/{dataset_id}` and only operate on datasets owned by the token's user. See [the API guide](docs/ACCOUNTS_TRANSACTIONS_API.md) for endpoint details, filters, pagination, and request examples. Create a dataset first with `POST /api/v1/datasets`.

## Dataset Management and CSV Imports

Dataset lifecycle, seeded synthetic data generation, and atomic CSV import endpoints are documented in [the Phase 6 guide](docs/DATASETS_SYNTHETIC_CSV.md), with canonical [account](docs/examples/accounts.csv) and [transaction](docs/examples/transactions.csv) CSV examples.

The reusable, non-API NetworkX transaction graph engine and its metrics, filtering, bounded paths, and serialization semantics are documented in [the Phase 7 graph engine guide](docs/GRAPH_ENGINE.md).

The pure, deterministic Phase 8 suspicious-pattern detectors and their configuration, evidence contracts, bounds, and limitations are documented in [the detection engine guide](docs/DETECTION_ENGINE.md). Phase 9 persists multi-account and multi-transaction findings with per-analysis evidence snapshots, investigator lifecycle and assignment, and explainable finding/account risk scores. See [Risk Scoring and Finding Management](docs/RISK_SCORING_ALERTS.md) for the formula, default weights, API contracts, ownership rules, and limitations. `DetectionAlert` remains unchanged for its original transaction-level use.

Phase 10 adds a backend-only unsupervised anomaly analysis package with cutoff-safe account/transaction features, train-only preprocessing, Isolation Forest, novelty LOF, and K-Means. Grouped holdout evaluation uses only explicit ground-truth labels in a separate workflow. Model metadata is persisted by additive revision `b18f3a9d2c74`; fitted estimators remain process-local and are not serialized. ML findings pass through a controlled Phase 9 adapter without directly modifying risk scores. See [Machine Learning and Anomaly Detection](docs/MACHINE_LEARNING.md) for feature definitions, methodology, and limitations.

Phase 11 adds authenticated asynchronous analysis jobs backed by the existing Redis service and Celery workers. PostgreSQL stores job lifecycle and stage progress; task payloads contain only a job UUID and use JSON serialization. Start a worker and the periodic recovery scheduler from `backend/` using the commands in [Background Processing](docs/BACKGROUND_PROCESSING.md). The additive migration `c7e4a91d2f60` preserves existing analysis rows.

## Security & Secrets Management

- **NEVER** commit `.env` files to git. All credentials, passwords, and sensitive configurations are ignored by `.gitignore`.
- Use `.env.example` as a template for adding new environment variables.
- Use a different randomly generated `JWT_SECRET_KEY` in each environment. Replacing a key invalidates tokens signed with the previous key.
