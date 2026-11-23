import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers
from app.core.observability import JsonFormatter, RequestContextMiddleware


def make_test_app():
    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.add_middleware(RequestContextMiddleware)

    @test_app.get("/not-found")
    def not_found():
        raise HTTPException(status_code=404, detail="Resource not found.")

    @test_app.get("/invalid")
    def invalid(value: int):
        return {"value": value}

    @test_app.get("/crash")
    def crash():
        raise RuntimeError("sensitive internal detail")

    return test_app


def test_http_errors_use_shared_error_envelope():
    with TestClient(make_test_app()) as client:
        response = client.get("/not-found")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Resource not found."
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_validation_errors_do_not_echo_submitted_values():
    with TestClient(make_test_app()) as client:
        response = client.get("/invalid", params={"value": "account-secret"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "account-secret" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_unhandled_errors_are_normalized_without_exposing_exception():
    with TestClient(make_test_app()) as client:
        response = client.get("/crash")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_server_error"
    assert response.json()["error"]["message"] == "An unexpected error occurred."
    assert "sensitive internal detail" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_json_formatter_emits_structured_fields():
    record = logging.LogRecord(
        name="muletrace.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request.completed",
        args=(),
        exc_info=None,
    )
    record.request_id = "request-123"
    record.status_code = 200
    record.method = "GET"

    event = json.loads(JsonFormatter().format(record))

    assert event["message"] == "request.completed"
    assert event["request_id"] == "request-123"
    assert event["status_code"] == 200
    assert event["method"] == "GET"
