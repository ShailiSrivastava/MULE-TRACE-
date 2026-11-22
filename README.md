# MuleTrace

**MuleTrace** is a full-stack trace analysis and graph visualization platform. This repository provides a clean, modular foundation architected for decoupled frontend and backend development.

---

## Team & Collaboration

- **Collaborators**: Shaili & Raj
- **Repository**: [https://github.com/ShailiSrivastava/MULE-TRACE-](https://github.com/ShailiSrivastava/MULE-TRACE-)
- **Default Branch**: `main`

---

## Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Frontend** | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, Cytoscape.js, Recharts |
| **Backend** | Python 3, FastAPI, SQLAlchemy 2.0, PostgreSQL |
| **Testing** | Vitest, React Testing Library, Pytest, HTTPX |
| **API Testing** | Postman (Collection & Environment included) |

---

## Directory Structure

```text
MULE-TRACE/
├── .env.example              # Root environment template
├── .gitignore                # Comprehensive Git exclusions for Python, Node, & secrets
├── README.md                 # Project documentation and start guide
│
├── docs/                     # Architectural & team workflow documentation
│   ├── ARCHITECTURE.md       # High-level architecture & design
│   ├── CONTRIBUTING.md       # Git branching & collaboration guide
│   └── SETUP_GUIDE.md        # Comprehensive Windows setup walkthrough
│
├── backend/                  # FastAPI + SQLAlchemy backend
│   ├── .env.example          # Backend environment variable template
│   ├── pyproject.toml        # Pytest & tool configuration
│   ├── requirements.txt      # Python dependencies
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI entrypoint with CORS & health checks
│   │   └── core/
│   │       ├── __init__.py
│   │       ├── config.py     # Pydantic Settings configuration
│   │       └── database.py   # SQLAlchemy engine & session factory
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py       # Pytest fixtures and TestClient
│       └── test_health.py    # Health check & root API test suite
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
2. **Python** (3.10+): Verify with `python --version`.
3. **Git**: Verify with `git --version`.

---

### 1. Setting Up and Running the Backend

Open **PowerShell Terminal 1**:

```powershell
# Navigate into backend directory
cd backend

# Create a virtual environment
python -m venv .venv

# Enable script execution for this session and activate
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# Install backend dependencies
pip install -r requirements.txt

# Create your local environment file
Copy-Item .env.example .env

# Run backend unit tests
pytest

# Start the FastAPI server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- **API Root**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Health Check**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
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

## Security & Secrets Management

- **NEVER** commit `.env` files to git. All credentials, passwords, and sensitive configurations are ignored by `.gitignore`.
- Use `.env.example` as a template for adding new environment variables.
