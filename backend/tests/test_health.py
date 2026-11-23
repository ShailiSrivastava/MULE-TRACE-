from sqlalchemy.exc import SQLAlchemyError

from app.core.database import DatabaseNotConfiguredError


def test_root_endpoint(client):
    """Test the root endpoint returns 200 and expected metadata."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "project" in data
    assert data["docs_url"] == "/docs"


def test_health_check_endpoint(client):
    """Test the health check endpoint returns 200 and healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "muletrace-backend"
    assert data["version"] == "0.1.0"


def test_legacy_health_endpoint_includes_request_id(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.json() == {
        "status": "healthy",
        "service": "muletrace-backend",
        "version": "0.1.0",
    }


def test_liveness_endpoint_does_not_require_database(client):
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_readiness_endpoint_checks_database(client, monkeypatch):
    monkeypatch.setattr("app.api.health.check_database_connection", lambda: None)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_readiness_reports_database_unavailable(client, monkeypatch):
    def fail_connection_check():
        raise SQLAlchemyError("database is offline")

    monkeypatch.setattr(
        "app.api.health.check_database_connection", fail_connection_check
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "database is offline" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_readiness_reports_missing_database_configuration(client, monkeypatch):
    def fail_configuration_check():
        raise DatabaseNotConfiguredError("database configuration is missing")

    monkeypatch.setattr(
        "app.api.health.check_database_connection", fail_configuration_check
    )

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "database configuration is missing" not in response.text


def test_versioned_api_root(client):
    response = client.get("/api/v1")

    assert response.status_code == 200
    assert response.json() == {
        "project": "MuleTrace API",
        "api_version": "v1",
        "status": "online",
    }
