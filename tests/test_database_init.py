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


def test_init_db_uses_schema_without_migration_table(monkeypatch, tmp_path):
    config, database = _fresh_database(monkeypatch, tmp_path)

    database.init_db()

    with sqlite3.connect(config.DB_PATH) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "schema_migrations" not in tables
    assert "permissions" in columns


def test_init_db_uses_lightweight_indexes(monkeypatch, tmp_path):
    config, database = _fresh_database(monkeypatch, tmp_path)

    database.init_db()

    with sqlite3.connect(config.DB_PATH) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'index', 'trigger') AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
    assert "idx_reagents_name" not in names
    assert "idx_movements_to_snapshot_moved" not in names
    assert "idx_reagents_updated" in names
    assert "idx_reagents_storage_status_updated" in names
    assert "idx_validations_catalog_date" in names


def test_storage_nodes_schema_uses_single_space_model(monkeypatch, tmp_path):
    config, database = _fresh_database(monkeypatch, tmp_path)

    database.init_db()

    with sqlite3.connect(config.DB_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(storage_nodes)").fetchall()}
        root = conn.execute("SELECT node_type, space_type FROM storage_nodes WHERE id = 1").fetchone()
    assert {
        "id",
        "parent_id",
        "name",
        "node_type",
        "space_type",
        "location_code",
        "rows",
        "cols",
        "grid_row",
        "grid_col",
        "sort_order",
    } <= columns
    assert root == ("space", 5)
