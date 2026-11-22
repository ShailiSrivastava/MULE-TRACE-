# MuleTrace Architecture

This document describes the architectural foundation for the **MuleTrace** full-stack system.

## 1. High-Level Architecture Overview

MuleTrace is architected as a decoupled, multi-tier full-stack application:

```
+----------------------------------------------------------------+
|                         Browser / Client                       |
|               React (TypeScript) + Vite + Tailwind             |
|              Cytoscape.js (Graphs) + Recharts (Metrics)        |
+-------------------------------+--------------------------------+
                                |
                     HTTP / REST Requests
                     JSON Data Exchange
                                |
                                v
+-------------------------------+--------------------------------+
|                      Backend API (FastAPI)                     |
|           Endpoints, Middleware (CORS), Pydantic Config        |
+-------------------------------+--------------------------------+
                                |
                       SQLAlchemy 2.0 ORM
                                |
                                v
+-------------------------------+--------------------------------+
|                    Relational Database                         |
|                         PostgreSQL                             |
+----------------------------------------------------------------+
```

## 2. Directory Layout & Boundary Separation

- **`frontend/`**: Contains the client application built with Vite, React, and TypeScript.
  - UI styled using Tailwind CSS and shadcn/ui component conventions.
  - Visualization powered by Cytoscape.js (graph/network representations) and Recharts (analytics/metrics).
  - Tests powered by Vitest and React Testing Library.
- **`backend/`**: Contains the Python FastAPI service.
  - Modular structure (`app/core/` for configs and database connections).
  - Database access managed through SQLAlchemy `SessionLocal` dependencies.
  - Automated tests running via Pytest and FastAPI's HTTPX-based `TestClient`.
- **`postman/`**: Pre-configured Postman collections and environments for manual and automated API validation.
- **`docs/`**: Setup, architecture, and team collaboration documentation.

## 3. Communication Contract

- Frontend communicates with Backend using standard RESTful HTTP methods.
- Default local frontend origin: `http://localhost:5173`
- Default local backend API: `http://localhost:8000`
- Interactive OpenAPI documentation is accessible at `http://localhost:8000/docs`.
- Health probes are available at `http://localhost:8000/health`.

## 4. Environment and Secrets Strategy

- All sensitive keys, database credentials, and machine-specific endpoints are isolated in `.env` files.
- `.env` files are ignored by git via `.gitignore`.
- Template configurations are documented in `.env.example`, `frontend/.env.example`, and `backend/.env.example`.
