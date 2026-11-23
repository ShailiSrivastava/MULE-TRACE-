"""Check Celery worker responsiveness without exposing worker diagnostics."""

from __future__ import annotations

import sys

from app.tasks.celery_app import celery_app


def main() -> int:
    replies = celery_app.control.ping(timeout=5.0)
    if not replies:
        print("No MuleTrace Celery worker replied to the health check.")
        return 1
    print(f"MuleTrace Celery worker health: healthy ({len(replies)} reply/replies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
