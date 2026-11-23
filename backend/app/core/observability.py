"""Structured application logging and request correlation."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from starlette.responses import JSONResponse

from app.core.metrics import record_http_request

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
ErrorEventHook = Callable[[dict[str, str | int]], None]
_error_event_hooks: list[ErrorEventHook] = []
_SENSITIVE_LOG_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password|token|secret|dsn|database_url)=([^&\s]+)"), r"\1=[REDACTED]"),
    (
        re.compile(r"(?i)(postgres(?:ql)?(?:\+[^:/\s]+)?|redis)://[^\s]+"),
        r"\1://[REDACTED]",
    ),
)


class RequestBodyTooLarge(Exception):
    """Raised internally when a streamed request exceeds the configured cap."""


def register_error_event_hook(hook: ErrorEventHook) -> Callable[[], None]:
    """Register an error-monitor callback receiving safe metadata only."""
    _error_event_hooks.append(hook)

    def unregister() -> None:
        if hook in _error_event_hooks:
            _error_event_hooks.remove(hook)

    return unregister


def report_error_event(event: dict[str, str | int]) -> None:
    """Notify integrations without forwarding exception messages or request data."""
    safe_event = {
        key: value
        for key, value in event.items()
        if key in {"request_id", "exception_type", "method", "route", "status_code"}
    }
    for hook in tuple(_error_event_hooks):
        try:
            hook(safe_event)
        except Exception:  # noqa: BLE001 - external monitoring callbacks are isolated.
            logging.getLogger("muletrace.observability").error(
                "error_monitor.hook_failed"
            )


class JsonFormatter(logging.Formatter):
    """Format application log records as one JSON object per line."""

    _structured_fields = (
        "method",
        "path",
        "status_code",
        "duration_ms",
        "query_duration_ms",
        "db_operation",
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
        message = record.getMessage()
        for pattern, replacement in _SENSITIVE_LOG_PATTERNS:
            message = pattern.sub(replacement, message)
        event: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": message,
        }
        request_id = getattr(record, "request_id", None) or request_id_context.get()
        if request_id:
            event["request_id"] = request_id

        for field in self._structured_fields:
            value = getattr(record, field, None)
            if value is not None:
                event[field] = value

        if record.exc_info:
            event.setdefault("exception_type", record.exc_info[0].__name__)

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
    """Add correlation/security headers, enforce body caps, and log safe outcomes."""

    def __init__(
        self,
        app: Any,
        *,
        max_request_body_bytes: int = 12_582_912,
        production: bool = False,
    ) -> None:
        self.app = app
        self.max_request_body_bytes = max_request_body_bytes
        self.production = production
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
        body_bytes_received = 0

        async def receive_with_body_limit() -> dict[str, Any]:
            nonlocal body_bytes_received
            message = await receive()
            if message["type"] == "http.request":
                body_bytes_received += len(message.get("body", b""))
                if body_bytes_received > self.max_request_body_bytes:
                    raise RequestBodyTooLarge
            return message

        async def send_with_request_id(message: dict[str, Any]) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                security_headers = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                }
                if scope.get("path", "").startswith(("/api/", "/health/")):
                    security_headers[b"cache-control"] = b"no-store"
                if self.production:
                    security_headers[b"strict-transport-security"] = (
                        b"max-age=31536000; includeSubDomains"
                    )
                replaced_headers = {b"x-request-id", b"server", *security_headers}
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in replaced_headers
                ]
                headers.extend(security_headers.items())
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        async def send_error(status: int, code: str, message: str) -> None:
            response = JSONResponse(
                status_code=status,
                content={
                    "error": {
                        "code": code,
                        "message": message,
                        "request_id": request_id,
                    }
                },
            )
            await response(scope, receive, send_with_request_id)

        try:
            content_lengths = [
                value
                for name, value in scope.get("headers", [])
                if name.lower() == b"content-length"
            ]
            if content_lengths:
                try:
                    content_length = int(content_lengths[0])
                except ValueError:
                    await send_error(400, "bad_request", "Invalid Content-Length header.")
                    return
                if content_length < 0:
                    await send_error(400, "bad_request", "Invalid Content-Length header.")
                    return
                if content_length > self.max_request_body_bytes:
                    raise RequestBodyTooLarge
            await self.app(scope, receive_with_body_limit, send_with_request_id)
        except RequestBodyTooLarge:
            self.logger.warning("request.body_too_large")
            await send_error(
                413,
                "request_too_large",
                "The request body exceeds the configured size limit.",
            )
        except Exception as exc:
            route = scope.get("route")
            route_path = getattr(route, "path", "<unmatched>")
            self.logger.error(
                "request.unhandled_exception",
                extra={"exception_type": type(exc).__name__},
            )
            report_error_event(
                {
                    "request_id": request_id,
                    "exception_type": type(exc).__name__,
                    "method": scope.get("method", ""),
                    "route": route_path,
                    "status_code": 500,
                }
            )
            if response_started:
                raise
            await send_error(
                500, "internal_server_error", "An unexpected error occurred."
            )
        finally:
            route = scope.get("route")
            path = getattr(route, "path", "<unmatched>")
            duration_seconds = time.perf_counter() - started_at
            record_http_request(
                method=scope.get("method", ""),
                route=path,
                status_code=status_code,
                duration_seconds=duration_seconds,
            )
            self.logger.info(
                "request.completed",
                extra={
                    "method": scope.get("method", ""),
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": round(duration_seconds * 1000, 2),
                },
            )
            request_id_context.reset(token)
