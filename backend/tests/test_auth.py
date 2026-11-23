from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import get_db, get_engine
from app.core.model_base import Base
from app.main import app
from app.models import AuditLog, User, UserRole
from app.security.passwords import hash_password, verify_password
from app.security.tokens import TokenConfigurationError, create_access_token
from app.services.auth import (
    AdministratorLockoutError,
    bootstrap_first_admin,
    register_user,
)

TEST_JWT_SECRET = "test-only-jwt-secret-value-at-least-32-bytes-long"
VALID_PASSWORD = "StrongPassphrase2026!"


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = factory()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", SecretStr(TEST_JWT_SECRET))
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 1)
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture
def postgres_session() -> Generator[Session, None, None]:
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required for this integration test.")
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


def _register(client: TestClient, email: str = "analyst@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": VALID_PASSWORD,
            "display_name": "Test Analyst",
        },
    )


def _login(client: TestClient, email: str, password: str = VALID_PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _insert_admin(factory: sessionmaker) -> User:
    with factory() as db:
        admin = User(
            email=f"admin-{uuid4().hex}@example.com",
            password_hash=hash_password(VALID_PASSWORD),
            role=UserRole.ADMIN.value,
            display_name="Test Administrator",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin


def test_password_hashing_uses_argon2_and_verifies_without_plaintext():
    hashed = hash_password(VALID_PASSWORD)

    assert hashed.startswith("$argon2id$")
    assert VALID_PASSWORD not in hashed
    assert verify_password(VALID_PASSWORD, hashed)
    assert not verify_password("wrong password", hashed)


def test_successful_registration_login_and_current_user(auth_client):
    client, factory = auth_client
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "Analyst@Example.com",
            "password": VALID_PASSWORD,
            "display_name": "Test Analyst",
            "role": "ADMIN",
        },
    )

    assert registration.status_code == 201
    body = registration.json()
    assert body["email"] == "analyst@example.com"
    assert body["role"] == "ANALYST"
    assert body["is_active"] is True
    assert "password_hash" not in body
    assert VALID_PASSWORD not in registration.text

    with factory() as db:
        user = db.scalar(select(User).where(User.email == "analyst@example.com"))
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        user_id = user.id
        registration_event = db.scalar(
            select(AuditLog).where(
                AuditLog.event_type == "auth.registration.succeeded",
                AuditLog.entity_id == user.id,
            )
        )
        assert registration_event.request_id == registration.headers["x-request-id"]

    login_response = _login(client, "analyst@example.com")
    assert login_response.status_code == 200
    token_body = login_response.json()
    assert token_body["token_type"] == "bearer"
    assert token_body["expires_in"] == 60

    current = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_body['access_token']}"},
    )
    assert current.status_code == 200
    assert current.json()["id"] == str(user_id)
    assert "password_hash" not in current.json()


def test_first_admin_bootstrap_requires_an_existing_active_account(auth_client):
    client, factory = auth_client
    registered = _register(client, "bootstrap@example.com")
    user_id = UUID(registered.json()["id"])

    with factory() as db:
        user = bootstrap_first_admin(db, user_id)
        assert user.role == UserRole.ADMIN.value
        assert (
            db.scalar(
                select(AuditLog).where(
                    AuditLog.event_type == "auth.admin.bootstrapped",
                    AuditLog.entity_id == user_id,
                )
            )
            is not None
        )

        with pytest.raises(AdministratorLockoutError, match="already exists"):
            bootstrap_first_admin(db, user_id)


def test_duplicate_email_registration_is_rejected_case_insensitively(auth_client):
    client, _ = auth_client
    assert _register(client, "same@example.com").status_code == 201

    duplicate = _register(client, "SAME@example.com")

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"


def test_weak_password_registration_is_rejected(auth_client):
    client, _ = auth_client

    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "short" not in response.text


def test_invalid_login_does_not_disclose_account_existence_and_is_audited(auth_client):
    client, factory = auth_client
    _register(client, "known@example.com")

    known = _login(client, "known@example.com", "WrongPassphrase2026!")
    unknown = _login(client, "missing@example.com", "WrongPassphrase2026!")

    assert known.status_code == unknown.status_code == 401
    assert known.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert known.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert "known@example.com" not in known.text
    assert "missing@example.com" not in unknown.text
    with factory() as db:
        failures = db.scalars(
            select(AuditLog).where(AuditLog.event_type == "auth.login.failed")
        ).all()
        assert len(failures) == 2
        assert all("email" not in row.details for row in failures)


def test_expired_and_malformed_tokens_are_rejected(auth_client):
    client, _ = auth_client
    user_response = _register(client)
    assert user_response.status_code == 201
    user_id = user_response.json()["id"]
    expired = create_access_token(user_id, expires_delta=timedelta(seconds=-5))
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": user_id,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
            "jti": str(uuid4()),
            "token_type": "access",
        },
        "another-secret-that-is-not-the-test-key",
        algorithm="HS256",
    )

    expired_response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    malformed_response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    forged_response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}
    )

    assert (
        expired_response.status_code
        == malformed_response.status_code
        == forged_response.status_code
        == 401
    )
    assert expired_response.json()["error"]["code"] == "unauthorized"
    assert malformed_response.json()["error"]["code"] == "unauthorized"
    assert forged_response.json()["error"]["code"] == "unauthorized"


def test_token_creation_fails_when_jwt_secret_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", None)

    with pytest.raises(TokenConfigurationError):
        create_access_token(uuid4())


def test_missing_authorization_header_returns_consistent_401(auth_client):
    client, _ = auth_client

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_deactivated_user_cannot_login_or_use_an_existing_token(auth_client):
    client, factory = auth_client
    registered = _register(client)
    login = _login(client, "analyst@example.com")
    token = login.json()["access_token"]
    with factory() as db:
        user = db.get(User, UUID(registered.json()["id"]))
        user.is_active = False
        db.commit()

    failed_login = _login(client, "analyst@example.com")
    failed_me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert failed_login.status_code == failed_me.status_code == 401
    assert failed_login.json()["error"]["message"] == "Email or password is incorrect."


def test_analyst_cannot_access_administrative_endpoints(auth_client):
    client, _ = auth_client
    registered = _register(client)
    token = _login(client, "analyst@example.com").json()["access_token"]

    response = client.patch(
        f"/api/v1/admin/users/{registered.json()['id']}/activation",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_admin_can_change_roles_and_activation_with_audit(auth_client):
    client, factory = auth_client
    analyst = _register(client)
    admin = _insert_admin(factory)
    admin_token = _login(client, admin.email).json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    changed_role = client.patch(
        f"/api/v1/admin/users/{analyst.json()['id']}/role",
        headers=headers,
        json={"role": "INVESTIGATOR"},
    )
    deactivated = client.patch(
        f"/api/v1/admin/users/{analyst.json()['id']}/activation",
        headers=headers,
        json={"is_active": False},
    )
    reactivated = client.patch(
        f"/api/v1/admin/users/{analyst.json()['id']}/activation",
        headers=headers,
        json={"is_active": True},
    )

    assert changed_role.status_code == 200
    assert changed_role.json()["role"] == "INVESTIGATOR"
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert reactivated.status_code == 200
    assert reactivated.json()["is_active"] is True
    with factory() as db:
        events = set(
            db.scalars(
                select(AuditLog.event_type).where(
                    AuditLog.entity_id == UUID(analyst.json()["id"])
                )
            ).all()
        )
    assert "auth.user.role_changed" in events
    assert "auth.user.deactivated" in events
    assert "auth.user.activated" in events


def test_admin_cannot_deactivate_themselves_or_last_active_admin(auth_client):
    client, factory = auth_client
    admin = _insert_admin(factory)
    token = _login(client, admin.email).json()["access_token"]

    response = client.patch(
        f"/api/v1/admin/users/{admin.id}/activation",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.integration
def test_registration_persists_argon2_hash_and_audit_in_postgres(postgres_session):
    email = f"auth-integration-{uuid4().hex}@example.com"
    user = register_user(
        postgres_session,
        email=email,
        password=VALID_PASSWORD,
        display_name="Integration Analyst",
    )

    persisted = postgres_session.scalar(select(User).where(User.id == user.id))
    audit = postgres_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == user.id,
            AuditLog.event_type == "auth.registration.succeeded",
        )
    )

    assert persisted is not None
    assert persisted.password_hash.startswith("$argon2id$")
    assert verify_password(VALID_PASSWORD, persisted.password_hash)
    assert audit is not None
