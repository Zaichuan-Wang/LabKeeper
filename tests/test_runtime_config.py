import importlib
import os
import sys
from pathlib import Path


ENV_FILE = Path(__file__).resolve().parents[1] / "config" / ".env"


def reload_config(monkeypatch, **values):
    original_exists = Path.exists

    def exists_without_local_env(path):
        if path == ENV_FILE:
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", exists_without_local_env)
    for key in list(os.environ):
        if key.startswith("LABKEEPER_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("core.config", None)
    return importlib.import_module("core.config")


def test_production_rejects_placeholder_secret(monkeypatch):
    try:
        reload_config(
            monkeypatch,
            LABKEEPER_ENV="production",
            LABKEEPER_API_SECRET="change-this-secret-before-shared-deployment",
        )
    except RuntimeError as exc:
        assert "LABKEEPER_API_SECRET" in str(exc)
    else:
        raise AssertionError("placeholder production secret should be rejected")


def test_production_requires_explicit_cors_origins(monkeypatch):
    try:
        reload_config(
            monkeypatch,
            LABKEEPER_ENV="production",
            LABKEEPER_API_SECRET="prod-secret",
        )
    except RuntimeError as exc:
        assert "LABKEEPER_CORS_ORIGINS" in str(exc)
    else:
        raise AssertionError("production CORS origins should be explicit")


def test_production_rejects_placeholder_initial_password(monkeypatch):
    try:
        reload_config(
            monkeypatch,
            LABKEEPER_ENV="production",
            LABKEEPER_API_SECRET="prod-secret",
            LABKEEPER_INITIAL_PASSWORD="change-this-initial-password",
            LABKEEPER_CORS_ORIGINS="https://lab.example.com",
        )
    except RuntimeError as exc:
        assert "LABKEEPER_INITIAL_PASSWORD" in str(exc)
    else:
        raise AssertionError("placeholder production initial password should be rejected")


def test_production_accepts_safe_initial_password(monkeypatch):
    config = reload_config(
        monkeypatch,
        LABKEEPER_ENV="production",
        LABKEEPER_API_SECRET="prod-secret",
        LABKEEPER_INITIAL_PASSWORD="safe-initial-password",
        LABKEEPER_CORS_ORIGINS="https://lab.example.com",
    )
    assert config.INITIAL_PASSWORD == "safe-initial-password"
    assert config.APP_VERSION == "1.0.0"


def test_version_can_be_overridden(monkeypatch):
    config = reload_config(monkeypatch, LABKEEPER_ENV="development", LABKEEPER_VERSION="1.2.3")
    assert config.APP_VERSION == "1.2.3"


def test_devtools_enabled_only_outside_production(monkeypatch):
    config = reload_config(monkeypatch, LABKEEPER_ENV="development", LABKEEPER_ENABLE_DEVTOOLS="1")
    assert config.ENABLE_DEVTOOLS is True

    config = reload_config(
        monkeypatch,
        LABKEEPER_ENV="production",
        LABKEEPER_ENABLE_DEVTOOLS="1",
        LABKEEPER_API_SECRET="prod-secret",
        LABKEEPER_INITIAL_PASSWORD="safe-initial-password",
        LABKEEPER_CORS_ORIGINS="https://lab.example.com",
    )
    assert config.ENABLE_DEVTOOLS is False
