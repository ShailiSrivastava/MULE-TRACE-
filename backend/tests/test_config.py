import pytest
from pydantic import ValidationError

from app.core.config import ENV_FILES, PROJECT_ROOT, Settings


def test_database_url_is_built_from_postgres_settings():
    settings = Settings(
        _env_file=None,
        POSTGRES_USER="trace_user",
        POSTGRES_PASSWORD="p@ss:/? word",
        POSTGRES_SERVER="db.internal",
        POSTGRES_PORT=5544,
        POSTGRES_DB="trace_dev",
    )

    url = settings.sqlalchemy_database_url

    assert url.drivername == "postgresql+psycopg2"
    assert url.username == "trace_user"
    assert url.password == "p@ss:/? word"
    assert url.host == "db.internal"
    assert url.port == 5544
    assert url.database == "trace_dev"


def test_explicit_database_url_overrides_postgres_settings():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="sqlite:///./muletrace-test.db",
        POSTGRES_DB="ignored_db",
    )

    assert settings.sqlalchemy_database_url.drivername == "sqlite"
    assert settings.sqlalchemy_database_url.database == "./muletrace-test.db"


def test_database_url_is_unavailable_without_explicit_url_or_credentials():
    settings = Settings(_env_file=None)

    assert settings.POSTGRES_USER is None
    assert settings.POSTGRES_PASSWORD is None
    assert settings.sqlalchemy_database_url is None


def test_backend_environment_file_overrides_root_environment_file(tmp_path):
    root_env = tmp_path / "root.env"
    backend_env = tmp_path / "backend.env"
    root_env.write_text("PROJECT_NAME=Root MuleTrace\n", encoding="utf-8")
    backend_env.write_text("PROJECT_NAME=Backend MuleTrace\n", encoding="utf-8")

    settings = Settings(_env_file=(root_env, backend_env))

    assert settings.PROJECT_NAME == "Backend MuleTrace"


def test_config_uses_documented_environment_file_paths():
    assert ENV_FILES == (PROJECT_ROOT / ".env", PROJECT_ROOT / "backend" / ".env")
    assert Settings.model_config["env_file"] == ENV_FILES


def test_jwt_secret_has_no_hardcoded_default_and_loads_from_env_file(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    secret = "environment-only-secret-value-with-at-least-32-characters"
    env_file = tmp_path / "auth.env"
    env_file.write_text(
        f"JWT_SECRET_KEY={secret}\nJWT_ISSUER=integration-test\n",
        encoding="utf-8",
    )

    unconfigured = Settings(_env_file=None)
    configured = Settings(_env_file=env_file)

    assert unconfigured.JWT_SECRET_KEY is None
    assert configured.JWT_SECRET_KEY.get_secret_value() == secret
    assert configured.JWT_ISSUER == "integration-test"


def test_process_environment_overrides_both_environment_files(tmp_path, monkeypatch):
    root_env = tmp_path / "root.env"
    backend_env = tmp_path / "backend.env"
    root_env.write_text("PROJECT_NAME=Root MuleTrace\n", encoding="utf-8")
    backend_env.write_text("PROJECT_NAME=Backend MuleTrace\n", encoding="utf-8")
    monkeypatch.setenv("PROJECT_NAME", "Process MuleTrace")

    settings = Settings(_env_file=(root_env, backend_env))

    assert settings.PROJECT_NAME == "Process MuleTrace"


def test_empty_database_url_override_uses_postgres_settings(tmp_path):
    env_file = tmp_path / "backend.env"
    env_file.write_text(
        "DATABASE_URL=\nPOSTGRES_USER=environment_user\n"
        "POSTGRES_PASSWORD=environment_password\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.sqlalchemy_database_url.password == "environment_password"


@pytest.mark.parametrize("invalid_port", [0, 65536])
def test_api_port_is_validated(invalid_port):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, API_PORT=invalid_port)


def test_log_level_is_validated():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, LOG_LEVEL="TRACE")


def test_celery_settings_load_from_documented_environment_files(tmp_path, monkeypatch):
    root_env = tmp_path / ".env"
    backend_env = tmp_path / "backend.env"
    root_env.write_text(
        "REDIS_HOST=root-redis\nREDIS_PASSWORD=root-password\n",
        encoding="utf-8",
    )
    backend_env.write_text(
        "REDIS_HOST=backend-redis\nREDIS_PASSWORD=backend password\n"
        "ANALYSIS_MAX_RETRIES=2\n",
        encoding="utf-8",
    )
    for key in (
        "REDIS_HOST",
        "REDIS_PASSWORD",
        "CELERY_BROKER_URL",
        "ANALYSIS_MAX_RETRIES",
    ):
        monkeypatch.delenv(key, raising=False)

    configured = Settings(_env_file=(root_env, backend_env))

    assert configured.REDIS_HOST == "backend-redis"
    assert configured.REDIS_PASSWORD.get_secret_value() == "backend password"
    assert configured.ANALYSIS_MAX_RETRIES == 2
    assert configured.celery_broker_url == (
        "redis://:backend%20password@backend-redis:6379/0"
    )
