import os
import sys
import sqlite3
import tempfile
from pathlib import Path

import pytest

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
