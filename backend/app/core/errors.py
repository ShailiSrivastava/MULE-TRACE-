"""Consistent API error response models and exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.observability import request_id_context


def _request_id() -> str:
    return request_id_context.get() or "unknown"


def _http_error_code(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        503: "service_unavailable",
    }.get(status_code, "http_error")


def error_body(
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the shared error envelope used by handlers and middleware."""
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id or _request_id(),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    message = (
        exc.detail
        if isinstance(exc.detail, str)
        else "The request could not be completed."
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(_http_error_code(exc.status_code), message),
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Exclude the submitted input values so malformed requests cannot echo
    # account identifiers, credentials, or other sensitive data in responses.
    details = [
        {
            "location": list(error.get("loc", ())),
            "message": error.get("msg", "Invalid value."),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=error_body(
            "validation_error",
            "Request validation failed.",
            details=details,
        ),
    )


async def database_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """Return a safe database failure envelope without exposing driver details."""

    return JSONResponse(
        status_code=503,
        content=error_body(
            "service_unavailable",
            "The database operation could not be completed.",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install API handlers for HTTP and request validation errors."""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(SQLAlchemyError, database_exception_handler)
