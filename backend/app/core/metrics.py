"""Low-cardinality in-process HTTP metrics for Prometheus scrapes."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

MetricKey = tuple[str, str, str]
_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
_lock = Lock()
_requests: defaultdict[MetricKey, int] = defaultdict(int)
_duration_sum: defaultdict[MetricKey, float] = defaultdict(float)
_duration_buckets: defaultdict[MetricKey, list[int]] = defaultdict(
    lambda: [0] * (len(_BUCKETS) + 1)
)
_database_queries = 0
_slow_database_queries = 0
_database_query_duration = 0.0


def record_http_request(
    *, method: str, route: str, status_code: int, duration_seconds: float
) -> None:
    """Record one completed response using route templates, never raw URLs."""
    key = (method, route, str(status_code))
    with _lock:
        _requests[key] += 1
        _duration_sum[key] += duration_seconds
        buckets = _duration_buckets[key]
        for index, boundary in enumerate(_BUCKETS):
            if duration_seconds <= boundary:
                buckets[index] += 1
        buckets[-1] += 1


def record_database_query(duration_seconds: float, *, slow: bool) -> None:
    """Record aggregate query telemetry without storing SQL or bind values."""
    global _database_queries, _slow_database_queries, _database_query_duration
    with _lock:
        _database_queries += 1
        _database_query_duration += duration_seconds
        if slow:
            _slow_database_queries += 1


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def render_prometheus_metrics() -> str:
    """Render current process counters without infrastructure or user details."""
    with _lock:
        requests = dict(_requests)
        duration_sums = dict(_duration_sum)
        duration_buckets = {key: list(value) for key, value in _duration_buckets.items()}

    lines = [
        "# HELP muletrace_http_requests_total Completed HTTP responses.",
        "# TYPE muletrace_http_requests_total counter",
    ]
    for (method, route, status), count in sorted(requests.items()):
        labels = (
            f'method="{_escape_label(method)}",'
            f'route="{_escape_label(route)}",status="{status}"'
        )
        lines.append(f"muletrace_http_requests_total{{{labels}}} {count}")

    lines.extend(
        [
            "# HELP muletrace_http_request_duration_seconds HTTP response latency.",
            "# TYPE muletrace_http_request_duration_seconds histogram",
        ]
    )
    for key in sorted(duration_buckets):
        method, route, status = key
        base = (
            f'method="{_escape_label(method)}",'
            f'route="{_escape_label(route)}",status="{status}"'
        )
        values = duration_buckets[key]
        for index, boundary in enumerate(_BUCKETS):
            lines.append(
                "muletrace_http_request_duration_seconds_bucket{"
                f'{base},le="{boundary:g}"}} {values[index]}'
            )
        lines.append(
            "muletrace_http_request_duration_seconds_bucket{"
            f'{base},le="+Inf"}} {values[-1]}'
        )
        lines.append(
            f"muletrace_http_request_duration_seconds_count{{{base}}} {values[-1]}"
        )
        lines.append(
            "muletrace_http_request_duration_seconds_sum{"
            f"{base}}} {duration_sums[key]:.6f}"
        )
    with _lock:
        database_queries = _database_queries
        slow_database_queries = _slow_database_queries
        database_query_duration = _database_query_duration
    lines.extend(
        [
            "# HELP muletrace_database_queries_total Completed database queries.",
            "# TYPE muletrace_database_queries_total counter",
            f"muletrace_database_queries_total {database_queries}",
            "# HELP muletrace_database_slow_queries_total Slow database queries.",
            "# TYPE muletrace_database_slow_queries_total counter",
            f"muletrace_database_slow_queries_total {slow_database_queries}",
            "# HELP muletrace_database_query_duration_seconds_sum Aggregate query time.",
            "# TYPE muletrace_database_query_duration_seconds_sum counter",
            f"muletrace_database_query_duration_seconds_sum {database_query_duration:.6f}",
        ]
    )
    return "\n".join(lines) + "\n"


def reset_http_metrics() -> None:
    """Reset counters for isolated tests; not exposed through the API."""
    global _database_queries, _slow_database_queries, _database_query_duration
    with _lock:
        _requests.clear()
        _duration_sum.clear()
        _duration_buckets.clear()
        _database_queries = 0
        _slow_database_queries = 0
        _database_query_duration = 0.0
