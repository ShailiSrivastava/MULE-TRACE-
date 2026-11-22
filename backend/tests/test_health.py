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
