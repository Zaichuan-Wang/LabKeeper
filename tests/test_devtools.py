"""开发工具接口集中在 dev_tools/ 下，便于正式部署时整体排除。"""

import sqlite3

from dev_tools import api as devtools_api


def test_devtools_runtime_config_route_reports_enabled_state(monkeypatch):
    monkeypatch.setattr(devtools_api.config, "ENABLE_DEVTOOLS", True)
    monkeypatch.setattr(devtools_api.config, "DEVTOOLS_ADMIN_USERNAME", "dev-admin")

    payload = devtools_api.runtime_config()

    assert payload["devtools_enabled"] is True
    assert payload["devtools_admin_username"] == "dev-admin"
    assert "dev_tools" in str(devtools_api.__file__)


def test_devtools_login_endpoint_is_under_devtools_prefix(monkeypatch, app_client):
    monkeypatch.setattr(devtools_api.config, "ENABLE_DEVTOOLS", True)
    monkeypatch.setattr(devtools_api.config, "DEVTOOLS_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(devtools_api.config, "DEVTOOLS_ADMIN_PASSWORD", "admin123")
    for route in app_client.app.routes:
        if getattr(route, "path", "") == "/api/devtools/login":
            route_config = route.endpoint.__globals__["config"]
            monkeypatch.setattr(route_config, "ENABLE_DEVTOOLS", True)
            monkeypatch.setattr(route_config, "DEVTOOLS_ADMIN_USERNAME", "admin")
            monkeypatch.setattr(route_config, "DEVTOOLS_ADMIN_PASSWORD", "admin123")

    response = app_client.post("/api/devtools/login", json={})

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "admin"


def test_devtools_login_rejects_when_disabled(monkeypatch, app_client):
    monkeypatch.setattr(devtools_api.config, "ENABLE_DEVTOOLS", False)

    response = app_client.post("/api/devtools/login", json={})

    assert response.status_code == 403


def test_load_demo_database_generates_missing_demo(tmp_path, monkeypatch):
    from db import database
    from services import backup

    demo_path = tmp_path / "demo.sqlite3"
    db_path = tmp_path / "loaded.sqlite3"
    backup_settings_path = tmp_path / "backup_settings.json"

    monkeypatch.setattr(devtools_api.config, "ENABLE_DEVTOOLS", True)
    monkeypatch.setattr(devtools_api, "DEMO_DB_PATH", demo_path)
    monkeypatch.setattr(devtools_api.config, "DB_PATH", db_path)
    monkeypatch.setattr(devtools_api.config, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(backup, "stop_scheduler", lambda: None)
    monkeypatch.setattr(backup, "start_scheduler", lambda: None)

    result = devtools_api.load_demo_database()

    assert result["ok"] is True
    assert result["message"] == "Demo 数据库已生成并载入"
    assert demo_path.exists()
    assert db_path.exists()
    assert result["stats"]["reagents"] > 0


def test_load_demo_database_replaces_open_sqlite_file(tmp_path, monkeypatch):
    from db import database
    from services import backup
    from dev_tools.build_demo_db import build_demo_database

    demo_path = tmp_path / "demo.sqlite3"
    db_path = tmp_path / "loaded.sqlite3"
    backup_settings_path = tmp_path / "backup_settings.json"
    build_demo_database(demo_path)

    monkeypatch.setattr(devtools_api.config, "ENABLE_DEVTOOLS", True)
    monkeypatch.setattr(devtools_api, "DEMO_DB_PATH", demo_path)
    monkeypatch.setattr(devtools_api.config, "DB_PATH", db_path)
    monkeypatch.setattr(devtools_api.config, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(backup, "stop_scheduler", lambda: None)
    monkeypatch.setattr(backup, "start_scheduler", lambda: None)

    database.init_db()
    open_conn = sqlite3.connect(db_path)
    try:
        result = devtools_api.load_demo_database()
    finally:
        open_conn.close()

    assert result["ok"] is True
    assert result["message"] == "Demo 数据库已载入"
    assert result["stats"]["reagents"] > 0
