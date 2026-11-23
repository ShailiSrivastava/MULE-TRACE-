from __future__ import annotations

import asyncio
import json
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis.exceptions import RedisError

from app.api.metrics import router as metrics_router
from app.core import database
from app.core import rate_limit as rate_limit_module
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.metrics import reset_http_metrics
from app.core.observability import (
    JsonFormatter,
    RequestContextMiddleware,
    register_error_event_hook,
    report_error_event,
)
from app.core.rate_limit import rate_limit, reset_process_rate_limits


def _test_app(*, max_body_bytes: int = 1_024, production: bool = False) -> FastAPI:
    application = FastAPI()
    register_exception_handlers(application)
    application.add_middleware(
        RequestContextMiddleware,
        max_request_body_bytes=max_body_bytes,
        production=production,
    )
    return application


def test_rate_limit_returns_consistent_429_and_retry_after():
    reset_process_rate_limits()
    application = _test_app()

    @application.get(
        "/limited",
        dependencies=[Depends(rate_limit("unit-test", limit=1, window_seconds=60))],
    )
    def limited_route():
        return {"status": "ok"}

    with TestClient(application) as client:
        assert client.get("/limited").status_code == 200
        response = client.get("/limited")

    assert response.status_code == 429
    assert response.headers["retry-after"]
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]
    assert response.json()["error"]["code"] == "rate_limited"
    reset_process_rate_limits()


def test_production_rate_limit_fails_closed_when_redis_is_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    class UnavailableRedis:
        def eval(self, script: str, numkeys: int, key: str, window: int):
            raise RedisError("redis host and password must not be returned")

    monkeypatch.setattr(rate_limit_module, "get_redis_client", UnavailableRedis)
    application = _test_app()

    @application.get(
        "/protected-write",
        dependencies=[Depends(rate_limit("unit-test-prod", limit=1, window_seconds=60))],
    )
    def protected_write():
        return {"status": "ok"}

    response = TestClient(application).get("/protected-write")

    assert response.status_code == 503
    assert "redis host" not in response.text
    assert response.json()["error"]["code"] == "service_unavailable"


def test_production_rate_limit_uses_an_atomic_redis_window(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    class CountingRedis:
        count = 0
        script = ""

        def eval(self, script: str, numkeys: int, key: str, window: int):
            self.script = script
            self.count += 1
            return [self.count, window - 1]

    redis_client = CountingRedis()
    monkeypatch.setattr(
        rate_limit_module, "get_redis_client", lambda: redis_client
    )
    application = _test_app()

    @application.get(
        "/distributed-limited",
        dependencies=[Depends(rate_limit("unit-test-redis", limit=1, window_seconds=60))],
    )
    def distributed_limited_route():
        return {"status": "ok"}

    with TestClient(application) as client:
        first = client.get("/distributed-limited")
        second = client.get("/distributed-limited")

    assert first.status_code == 200
    assert second.status_code == 429
    assert "INCR" in redis_client.script
    assert "EXPIRE" in redis_client.script


def test_request_body_limit_returns_correlated_413():
    application = _test_app(max_body_bytes=8)

    @application.post("/body")
    async def read_body(request: Request):
        return {"size": len(await request.body())}

    response = TestClient(application).post("/body", content=b"123456789")

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]


def test_invalid_content_length_returns_correlated_400():
    sent: list[dict] = []

    async def endpoint(scope, receive, send):
        raise AssertionError("invalid content length must be rejected first")

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    asyncio.run(
        RequestContextMiddleware(endpoint)(
            {
                "type": "http",
                "method": "POST",
                "path": "/body",
                "headers": [(b"content-length", b"invalid")],
            },
            receive,
            send,
        )
    )
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = next(message for message in sent if message["type"] == "http.response.body")
    response = json.loads(body["body"])
    request_id = dict(start["headers"])[b"x-request-id"].decode()

    assert start["status"] == 400
    assert response["error"]["code"] == "bad_request"
    assert response["error"]["request_id"] == request_id


def test_metrics_endpoint_is_disabled_or_requires_a_token(monkeypatch):
    reset_http_metrics()
    application = _test_app()
    application.include_router(metrics_router)

    @application.get("/sample")
    def sample():
        return {"status": "ok"}

    with TestClient(application) as client:
        disabled = client.get("/internal/metrics")
        assert disabled.status_code == 404

        monkeypatch.setattr(settings, "METRICS_ENABLED", True)
        monkeypatch.setattr(
            settings, "METRICS_TOKEN", SecretStr("metrics-test-token-long-enough-123456")
        )
        assert client.get("/sample").status_code == 200
        assert client.get("/internal/metrics").status_code == 401
        metrics = client.get(
            "/internal/metrics",
            headers={"X-Metrics-Token": "metrics-test-token-long-enough-123456"},
        )

    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    assert 'route="/sample"' in metrics.text
    assert "muletrace_database_queries_total" in metrics.text
    assert "metrics-test-token" not in metrics.text
    reset_http_metrics()


def test_security_headers_include_hsts_only_in_production_https():
    application = _test_app(production=True)

    @application.get("/")
    def root():
        return {"status": "ok"}

    response = TestClient(application, base_url="https://testserver").get("/")

    assert response.status_code == 200
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert response.headers["x-frame-options"] == "DENY"


def test_json_logging_redacts_credentials_and_never_serializes_exception_text():
    record = logging.LogRecord(
        name="muletrace.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=(
            "failed password=hunter2 token=access-value "
            "postgresql+psycopg2://user:secret@host/db"
        ),
        args=(),
        exc_info=(ValueError, ValueError("private financial row contents"), None),
    )

    formatted = JsonFormatter().format(record)
    data = json.loads(formatted)

    assert "hunter2" not in formatted
    assert "access-value" not in formatted
    assert "user:secret" not in formatted
    assert "private financial row contents" not in formatted
    assert data["exception_type"] == "ValueError"


def test_application_shutdown_disposes_database_and_redis(monkeypatch):
    from app.main import lifespan

    class EngineStub:
        disposed = False

        def dispose(self):
            self.disposed = True

    engine_stub = EngineStub()
    redis_closed = []
    monkeypatch.setattr(database, "engine", engine_stub)
    monkeypatch.setattr("app.main.close_redis_client", lambda: redis_closed.append(True))
    application = FastAPI(lifespan=lifespan)

    with TestClient(application):
        pass

    assert engine_stub.disposed is True
    assert redis_closed == [True]


def test_error_monitor_hook_receives_only_safe_metadata():
    observed: list[dict[str, str | int]] = []
    unregister = register_error_event_hook(observed.append)
    try:
        report_error_event(
            {
                "request_id": "test-correlation-id",
                "exception_type": "RuntimeError",
                "method": "POST",
                "route": "/api/v1/auth/login",
                "status_code": 500,
                "password": "must-not-be-forwarded",
                "financial_record": "must-not-be-forwarded",
            }
        )
    finally:
        unregister()

    assert observed == [
        {
            "request_id": "test-correlation-id",
            "exception_type": "RuntimeError",
            "method": "POST",
            "route": "/api/v1/auth/login",
            "status_code": 500,
        }
    ]
