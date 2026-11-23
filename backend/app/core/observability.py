"""Structured application logging and request correlation."""

from __future__ import annotations

import json
import logging
import sys
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.responses import JSONResponse

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    """Format application log records as one JSON object per line."""

    _structured_fields = (
        "method",
        "path",
        "status_code",
        "duration_ms",
        "exception_type",
        "analysis_job_id",
        "dataset_id",
        "stage",
        "queue",
        "status",
        "retry_count",
        "recovered_count",
        "failed_count",
    )

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_context.get()
        if request_id:
            event["request_id"] = request_id

        for field in self._structured_fields:
            value = getattr(record, field, None)
            if value is not None:
                event[field] = value

        if record.exc_info:
            event["exception"] = self.formatException(record.exc_info)

        return json.dumps(event, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure the MuleTrace logger without changing third-party loggers."""
    logger = logging.getLogger("muletrace")
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


class RequestContextMiddleware:
    """Attach a request ID, log HTTP outcomes, and normalize uncaught errors."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.logger = logging.getLogger("muletrace.http")

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        token = request_id_context.set(request_id)
        started_at = time.perf_counter()
        response_started = False
        status_code = 500

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            self.logger.exception(
                "request.unhandled_exception",
                extra={"exception_type": type(exc).__name__},
            )
            if response_started:
                raise

            body = {
                "error": {
                    "code": "internal_server_error",
                    "message": "An unexpected error occurred.",
                    "request_id": request_id,
                }
            }
            response = JSONResponse(status_code=500, content=body)
            await response(scope, receive, send_with_request_id)
        finally:
            route = scope.get("route")
            path = getattr(route, "path", "<unmatched>")
            self.logger.info(
                "request.completed",
                extra={
                    "method": scope.get("method", ""),
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            request_id_context.reset(token)
