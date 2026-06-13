import importlib
import sqlite3
import sys


def _fresh_database(monkeypatch, tmp_path):
    monkeypatch.setenv("LABKEEPER_ENV", "test")
    monkeypatch.setenv("LABKEEPER_ENABLE_DEV_TOOLS", "1")
    monkeypatch.setenv("LABKEEPER_INITIAL_ADMIN_PASSWORD", "admin123")
    sys.modules.pop("core.config", None)
    sys.modules.pop("db.database", None)
    config = importlib.import_module("core.config")
    config.DB_PATH = tmp_path / "init-test.sqlite3"
    database = importlib.import_module("db.database")
    database.DB_PATH = config.DB_PATH
    return config, database


def test_init_db_records_schema_version(monkeypatch, tmp_path):
    config, database = _fresh_database(monkeypatch, tmp_path)

    database.init_db()

    with sqlite3.connect(config.DB_PATH) as conn:
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert version == database.SCHEMA_VERSION


def test_init_db_adds_missing_safe_columns(monkeypatch, tmp_path):
    config, database = _fresh_database(monkeypatch, tmp_path)
    db_path = config.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO users (username, display_name, password_hash, role, is_active, created_at, updated_at)
            VALUES ('admin', '管理员', 'placeholder', 'admin', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')
            """
        )
        conn.commit()

    database.init_db()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "permissions" in columns
