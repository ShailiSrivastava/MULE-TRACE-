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
    monkeypatch.setattr("app.api.health.check_redis_connection", lambda: None)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


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


def test_readiness_hides_redis_failure_details(client, monkeypatch):
    monkeypatch.setattr("app.api.health.check_database_connection", lambda: None)

    def fail_redis_check():
        from redis.exceptions import RedisError

        raise RedisError("redis host and credentials should stay private")

    monkeypatch.setattr("app.api.health.check_redis_connection", fail_redis_check)
    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "redis host" not in response.text
    assert "checks" not in response.json()


def test_security_headers_are_added_to_api_responses(client):
    response = client.get("/health/live")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_versioned_api_root(client):
    response = client.get("/api/v1")

    assert response.status_code == 200
    assert response.json() == {
        "project": "MuleTrace API",
        "api_version": "v1",
        "status": "online",
    }
