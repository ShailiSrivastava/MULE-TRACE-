"""Token-protected operational metrics endpoint."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.core.metrics import render_prometheus_metrics

router = APIRouter(tags=["Operations"])


@router.get(
    "/internal/metrics",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
def read_metrics(
    metrics_token: Annotated[str | None, Header(alias="X-Metrics-Token")] = None,
) -> PlainTextResponse:
    """Expose low-cardinality process metrics only when explicitly enabled."""
    expected = settings.METRICS_TOKEN
    if not settings.METRICS_ENABLED or expected is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if metrics_token is None or not hmac.compare_digest(
        metrics_token, expected.get_secret_value()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Metrics authorization is required.",
        )
    return PlainTextResponse(
        render_prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
