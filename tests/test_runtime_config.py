import importlib
import os
import sys


def reload_config(monkeypatch, **values):
    for key in list(os.environ):
        if key.startswith("LABKEEPER_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("core.config", None)
    return importlib.import_module("core.config")


def test_dev_tools_enabled_only_outside_production(monkeypatch):
    config = reload_config(monkeypatch, LABKEEPER_ENV="development")
    assert config.ENABLE_DEV_TOOLS is True

    config = reload_config(
        monkeypatch,
        LABKEEPER_ENV="production",
        LABKEEPER_ENABLE_DEV_TOOLS="1",
        LABKEEPER_API_SECRET="prod-secret",
        LABKEEPER_CORS_ORIGINS="https://lab.example.com",
    )
    assert config.ENABLE_DEV_TOOLS is False


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


def test_production_rejects_placeholder_initial_admin_password(monkeypatch, tmp_path):
    config = reload_config(
        monkeypatch,
        LABKEEPER_ENV="production",
        LABKEEPER_API_SECRET="prod-secret",
        LABKEEPER_INITIAL_ADMIN_PASSWORD="change-this-admin-password",
        LABKEEPER_CORS_ORIGINS="https://lab.example.com",
    )
    config.DB_PATH = tmp_path / "prod.sqlite3"
    sys.modules.pop("db.database", None)
    database = importlib.import_module("db.database")
    try:
        database.init_db()
    except RuntimeError as exc:
        assert "LABKEEPER_INITIAL_ADMIN_PASSWORD" in str(exc)
    else:
        raise AssertionError("placeholder production admin password should be rejected")
