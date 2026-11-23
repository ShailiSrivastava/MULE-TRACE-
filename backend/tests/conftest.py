import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import reset_process_rate_limits
from app.main import app


@pytest.fixture(autouse=True)
def isolate_process_rate_limits():
    """Keep development/test limiter state from leaking between test cases."""
    reset_process_rate_limits()
    yield
    reset_process_rate_limits()


@pytest.fixture(scope="module")
def client():
    """Module-scoped FastAPI test client."""
    with TestClient(app) as test_client:
        yield test_client
