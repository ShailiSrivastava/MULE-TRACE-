"""Argon2id password hashing and verification."""

from __future__ import annotations

import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

password_hasher = PasswordHasher()


def validate_password(password: str) -> None:
    """Enforce the registration password length policy."""

    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long.")
    if len(password) > 128:
        raise ValueError("Password must be no more than 128 characters long.")


def hash_password(password: str) -> str:
    """Hash a new password using the Argon2id password hasher."""

    validate_password(password)
    return password_hasher.hash(password)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """Create a process-local hash for timing-balanced unknown-user logins."""

    return password_hasher.hash(secrets.token_urlsafe(32))


# Warm the dummy hash at startup so the first unknown-user login does not pay
# for an additional hash-generation step relative to a known-user login.
_dummy_password_hash()


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Verify a password while doing an Argon2 check for unknown legacy users."""

    hash_to_check = stored_hash or _dummy_password_hash()
    try:
        verified = password_hasher.verify(hash_to_check, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
    return bool(stored_hash and verified)
