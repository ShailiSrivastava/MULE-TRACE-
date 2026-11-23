"""Operator-only administration commands using the configured database."""

from __future__ import annotations

import argparse
from uuid import UUID

from app.core.database import SessionLocal, get_engine
from app.services.auth import AdministratorLockoutError, bootstrap_first_admin


def _bootstrap_admin(user_id: UUID) -> int:
    try:
        get_engine()
        with SessionLocal() as db:
            user = bootstrap_first_admin(db, user_id)
    except (AdministratorLockoutError, LookupError) as exc:
        print(str(exc))
        return 1
    print(f"Bootstrapped first administrator: {user.id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap = subparsers.add_parser(
        "bootstrap-admin",
        help="Promote an existing account when no active admin exists",
    )
    bootstrap.add_argument("--user-id", type=UUID, required=True)
    args = parser.parse_args()
    return _bootstrap_admin(args.user_id)


if __name__ == "__main__":
    raise SystemExit(main())
