import run
from app.core.config import settings
from app.main import create_app


def test_server_entrypoint_uses_configured_server_settings(monkeypatch):
    captured = {}

    def fake_uvicorn_run(application, **options):
        captured["application"] = application
        captured.update(options)

    monkeypatch.setattr(run.uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setattr(run.settings, "API_HOST", "0.0.0.0")
    monkeypatch.setattr(run.settings, "API_PORT", 8123)
    monkeypatch.setattr(run.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(run.settings, "LOG_LEVEL", "WARNING")

    run.main()

    assert captured == {
        "application": "app.main:app",
        "host": "0.0.0.0",
        "port": 8123,
        "reload": False,
        "log_level": "warning",
        "access_log": False,
        "proxy_headers": False,
        "forwarded_allow_ips": "127.0.0.1",
    }


def test_debug_mode_is_disabled_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    application = create_app()

    assert application.debug is False
