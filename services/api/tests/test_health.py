import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def test_health_returns_service_status() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # The service name is environment-configurable, so compare against the
    # settings the app was built with rather than a hard-coded default.
    assert body["service"] == get_settings().service_name
    assert set(body) == {"status", "service"}


def test_settings_defaults_without_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COACHLENS_API_TITLE", raising=False)
    monkeypatch.delenv("COACHLENS_API_SERVICE_NAME", raising=False)

    settings = Settings(_env_file=None)

    assert settings.title == "CoachLens API"
    assert settings.service_name == "coachlens-api"


def test_settings_read_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COACHLENS_API_TITLE", "Custom Title")
    monkeypatch.setenv("COACHLENS_API_SERVICE_NAME", "custom-service")
    # Unprefixed variables must not be picked up.
    monkeypatch.setenv("SERVICE_NAME", "wrong")

    settings = Settings(_env_file=None)

    assert settings.title == "Custom Title"
    assert settings.service_name == "custom-service"
