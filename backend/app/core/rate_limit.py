"""Redis-backed fixed-window limits with a development-only local fallback."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from threading import Lock
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.redis import get_redis_client

_memory_lock = Lock()
_memory_buckets: dict[str, tuple[int, int]] = {}


def _consume_process_bucket(key: str, *, window: int) -> tuple[int, int]:
    now = int(time.time())
    window_id = now // window
    retry_after = max(1, window - now % window)
    with _memory_lock:
        previous_window, count = _memory_buckets.get(key, (window_id, 0))
        if previous_window != window_id:
            count = 0
        count += 1
        _memory_buckets[key] = (window_id, count)
    return count, retry_after


def _consume_redis_bucket(key: str, *, window: int) -> tuple[int, int]:
    now = int(time.time())
    window_id = now // window
    redis_key = f"muletrace:ratelimit:{key}:{window_id}"
    client = get_redis_client()
    result = client.eval(
        "local count = redis.call('INCR', KEYS[1]); "
        "if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
        "return {count, redis.call('TTL', KEYS[1])}",
        1,
        redis_key,
        window,
    )
    count, ttl = (int(value) for value in result)
    return count, max(1, ttl if ttl > 0 else window)


def rate_limit(name: str, *, limit: int, window_seconds: int) -> Callable:
    """Create a route dependency keyed by a stable client IP hash and route ID."""

    async def enforce_limit(request: Request) -> None:
        client_host = request.client.host if request.client else "unknown"
        host_hash = hashlib.sha256(client_host.encode("utf-8")).hexdigest()[:24]
        key = f"{name}:{host_hash}"
        try:
            if settings.ENVIRONMENT == "production":
                count, retry_after = await run_in_threadpool(
                    _consume_redis_bucket,
                    key,
                    window=window_seconds,
                )
            else:
                count, retry_after = _consume_process_bucket(
                    key, window=window_seconds
                )
        except RedisError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The request protection service is unavailable.",
            ) from exc

        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )

    return enforce_limit


def reset_process_rate_limits() -> None:
    """Reset in-memory development buckets for isolated tests."""
    with _memory_lock:
        _memory_buckets.clear()


AuthRateLimit = Annotated[
    None,
    Depends(
        rate_limit(
            "auth",
            limit=settings.AUTH_RATE_LIMIT_REQUESTS,
            window_seconds=settings.AUTH_RATE_LIMIT_WINDOW_SECONDS,
        )
    ),
]

SensitiveWriteRateLimit = Annotated[
    None,
    Depends(rate_limit("sensitive-write", limit=20, window_seconds=60)),
]

CsvUploadRateLimit = Annotated[
    None,
    Depends(
        rate_limit(
            "csv-upload",
            limit=settings.CSV_UPLOAD_RATE_LIMIT_REQUESTS,
            window_seconds=settings.CSV_UPLOAD_RATE_LIMIT_WINDOW_SECONDS,
        )
    ),
]

CaseExportRateLimit = Annotated[
    None,
    Depends(rate_limit("case-export", limit=10, window_seconds=60)),
]
