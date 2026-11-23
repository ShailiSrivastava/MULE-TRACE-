import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_muletrace.db")

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, engine as app_engine, SessionLocal, get_db
from app.main import app
# models imported via app.main lifespan context

engine = app_engine
TestingSessionLocal = SessionLocal

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

application = app
application.dependency_overrides[get_db] = override_get_db

# rely on app lifespan for table creation and seeding

client = TestClient(application)

def test_auth_login():
    r = client.post("/api/v1/auth/login", json={"email": "analyst@muletrace.io", "password": "MuleTrace@2026"})
    assert r.status_code == 200
    assert "access_token" in r.json()

def test_dashboard():
    r = client.get("/api/v1/dashboard/overview")
    assert r.status_code == 200
    assert "total_monitored_volume" in r.json()

def test_transactions_list():
    r = client.get("/api/v1/transactions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

def test_graph():
    r = client.get("/api/v1/graph/network")
    assert r.status_code == 200
    assert "nodes" in r.json()

def test_alerts():
    r = client.get("/api/v1/alerts")
    assert r.status_code == 200

def test_cases():
    r = client.get("/api/v1/cases")
    assert r.status_code == 200

def test_risk():
    r = client.get("/api/v1/risk/analysis")
    assert r.status_code == 200
    assert "score_distribution" in r.json()

def test_reports():
    r = client.get("/api/v1/reports/export?report_type=transactions&format=json")
    assert r.status_code == 200