import os
import sys
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LABKEEPER_ENV", "test")
os.environ.setdefault("LABKEEPER_ENABLE_DEV_TOOLS", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


@pytest.fixture
def tmp_db(tmp_path):
    """创建临时 SQLite 数据库并初始化 schema，返回连接。"""
    db_path = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def patch_db(tmp_db, monkeypatch):
    """让 backend.database.connect() 返回临时数据库连接。"""
    import database
    original_connect = database.connect

    def _connect():
        return tmp_db

    monkeypatch.setattr(database, "connect", _connect)
    yield tmp_db
    monkeypatch.setattr(database, "connect", original_connect)


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """创建使用临时 SQLite 文件的 FastAPI TestClient。"""
    import config
    import database

    db_path = tmp_path / "api-test.sqlite3"
    options_path = tmp_path / "dropdown_options.json"
    backup_settings_path = tmp_path / "backup_settings.json"

    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "OPTIONS_CONFIG_PATH", options_path)
    monkeypatch.setattr(config, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(database, "DB_PATH", db_path)

    # backup.py imports DB_PATH/BACKUP_SETTINGS_PATH at module import time, so
    # patch its module globals too when it has already been loaded.
    import backup
    import options_config

    monkeypatch.setattr(backup, "DB_PATH", db_path)
    monkeypatch.setattr(backup, "BACKUP_DIR", db_path.parent / "backups")
    monkeypatch.setattr(backup, "BACKUP_SETTINGS_PATH", backup_settings_path)
    monkeypatch.setattr(options_config, "OPTIONS_CONFIG_PATH", options_path)

    from server import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_headers(app_client):
    response = app_client.post("/api/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}
