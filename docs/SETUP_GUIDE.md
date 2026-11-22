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
3. **Python (3.10 to 3.12+ recommended)**:
   - Verify in PowerShell:
     ```powershell
     python --version
     ```
4. **PostgreSQL**:
   - Optional for initial scaffold, required for full database operations.
   - You can use Postgres locally or a Docker container.

---

## 2. Backend Setup (FastAPI & Python)

Open a PowerShell terminal and navigate to the project directory:

```powershell
cd "c:\Users\shail\Downloads\mule trace\backend"
```

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

### Step 2.4: Set Up Local Environment Variables
Create your local `.env` file by copying the template:
```powershell
Copy-Item .env.example .env
```
*(Update database credentials in `.env` if using a local PostgreSQL instance)*

### Step 2.5: Run Backend Tests
Verify the installation by running the test suite:
```powershell
pytest
```

### Step 2.6: Start the Backend Server
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- API Root: `http://127.0.0.1:8000/`
- Health Endpoint: `http://127.0.0.1:8000/health`
- Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

---

## 3. Frontend Setup (React, Vite, TypeScript)

Open a **separate** PowerShell terminal window:

```powershell
cd "c:\Users\shail\Downloads\mule trace\frontend"
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

## 4. API Testing with Postman

1. Open Postman.
2. Click **Import** in the top left.
3. Select `postman/MuleTrace_API.postman_collection.json`.
4. Select `postman/MuleTrace_Local.postman_environment.json`.
5. In Postman, switch the active environment to **MuleTrace Local Environment**.
6. Run the **Get Root Info** and **Health Check** requests to confirm API readiness.
