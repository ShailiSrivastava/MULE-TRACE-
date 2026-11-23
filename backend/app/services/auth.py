"""Authentication workflows and audit events."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.observability import request_id_context
from app.models import AuditLog, User, UserRole
from app.security.passwords import hash_password, verify_password


class DuplicateEmailError(ValueError):
    """Raised when an email address is already registered."""


class AdministratorLockoutError(ValueError):
    """Raised when an operation would remove the last active administrator."""


def _record_auth_event(
    db: Session,
    *,
    event_type: str,
    actor_user_id: UUID | None = None,
    entity_type: str = "authentication",
    entity_id: UUID | None = None,
    details: dict[str, str] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=request_id_context.get(),
            details=details or {},
        )
    )


def register_user(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str | None,
) -> User:
    """Create a least-privileged account and log the result without secrets."""

    normalized_email = email.strip().casefold()
    existing = db.scalar(
        select(User.id).where(func.lower(User.email) == normalized_email)
    )
    if existing is not None:
        _record_auth_event(
            db,
            event_type="auth.registration.rejected",
            details={"reason": "duplicate_email"},
        )
        db.commit()
        raise DuplicateEmailError

    user = User(
        email=normalized_email,
        display_name=display_name,
        password_hash=hash_password(password),
        role=UserRole.ANALYST.value,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        _record_auth_event(
            db,
            event_type="auth.registration.rejected",
            details={"reason": "duplicate_email_or_constraint_conflict"},
        )
        db.commit()
        raise DuplicateEmailError from exc

    _record_auth_event(
        db,
        event_type="auth.registration.succeeded",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"role": UserRole.ANALYST.value},
    )
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User | None:
    """Verify credentials and active status, logging failures identically."""

    normalized_email = email.strip().casefold()
    user = db.scalar(select(User).where(func.lower(User.email) == normalized_email))
    password_is_valid = verify_password(
        password,
        user.password_hash if user is not None else None,
    )

    if user is None or not user.is_active or not password_is_valid:
        _record_auth_event(
            db,
            event_type="auth.login.failed",
            details={"reason": "invalid_credentials"},
        )
        db.commit()
        return None

    return user


def record_login_success(db: Session, user: User) -> None:
    _record_auth_event(
        db,
        event_type="auth.login.succeeded",
        actor_user_id=user.id,
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()


def _active_admin_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count(User.id)).where(
                User.role == UserRole.ADMIN.value,
                User.is_active.is_(True),
            )
        )
        or 0
    )


def set_user_activation(
    db: Session,
    *,
    target_user_id: UUID,
    is_active: bool,
    actor: User,
) -> User | None:
    """Activate or deactivate an account while preserving an admin account."""

    user = db.scalar(select(User).where(User.id == target_user_id).with_for_update())
    if user is None:
        return None

    if user.is_active and not is_active:
        if user.id == actor.id and user.role == UserRole.ADMIN.value:
            raise AdministratorLockoutError(
                "An administrator cannot deactivate themselves."
            )
        if user.role == UserRole.ADMIN.value and _active_admin_count(db) <= 1:
            raise AdministratorLockoutError(
                "At least one active administrator must remain."
            )

    if user.is_active != is_active:
        user.is_active = is_active
        _record_auth_event(
            db,
            event_type="auth.user.activated" if is_active else "auth.user.deactivated",
            actor_user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            details={"is_active": str(is_active).lower()},
        )
        db.commit()
        db.refresh(user)
    return user


def set_user_role(
    db: Session,
    *,
    target_user_id: UUID,
    role: UserRole,
    actor: User,
) -> User | None:
    """Change a role through an administrator-only workflow with audit history."""

    user = db.scalar(select(User).where(User.id == target_user_id).with_for_update())
    if user is None:
        return None

    role_value = role.value
    if (
        user.is_active
        and user.role == UserRole.ADMIN.value
        and role_value != UserRole.ADMIN.value
        and _active_admin_count(db) <= 1
    ):
        raise AdministratorLockoutError(
            "At least one active administrator must remain."
        )

    if user.role != role_value:
        previous_role = user.role
        user.role = role_value
        _record_auth_event(
            db,
            event_type="auth.user.role_changed",
            actor_user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            details={"previous_role": previous_role, "role": role_value},
        )
        db.commit()
        db.refresh(user)
    return user


def bootstrap_first_admin(db: Session, user_id: UUID) -> User:
    """Promote an active account only when no active administrator exists."""

    if _active_admin_count(db):
        raise AdministratorLockoutError(
            "An active administrator already exists; use the protected admin API."
        )

    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise LookupError("User not found.")
    if not user.is_active:
        raise AdministratorLockoutError("The bootstrap user must be active.")
    if user.password_hash is None:
        raise AdministratorLockoutError(
            "The bootstrap user must have registered a password first."
        )

    user.role = UserRole.ADMIN.value
    _record_auth_event(
        db,
        event_type="auth.admin.bootstrapped",
        entity_type="user",
        entity_id=user.id,
        details={"role": UserRole.ADMIN.value},
    )
    db.commit()
    db.refresh(user)
    return user
