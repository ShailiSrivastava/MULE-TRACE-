"""Shared Redis client for health checks and production request throttling."""

from __future__ import annotations

from redis import Redis

from app.core.config import settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    """Return the process-local Redis client without opening a connection yet."""
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.celery_broker_url,
            socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
            socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
            health_check_interval=30,
            decode_responses=True,
        )
    return _client


def check_redis_connection() -> None:
    """Raise a Redis client error if the configured broker cannot answer PING."""
    get_redis_client().ping()


def close_redis_client() -> None:
    """Close pooled Redis sockets during graceful API shutdown."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
