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
        reagent_columns = {row[1] for row in conn.execute("PRAGMA table_info(reagents)").fetchall()}
        sample_columns = {row[1] for row in conn.execute("PRAGMA table_info(clinical_samples)").fetchall()}
    assert "idx_reagents_name" not in names
    assert "idx_reagents_validation_updated" not in names
    assert "idx_movements_to_snapshot_moved" not in names
    assert "validation_status" not in reagent_columns
    assert "expiration_date" not in sample_columns
    assert "validation_status" not in sample_columns
    assert "idx_reagents_updated" in names
    assert "idx_reagents_storage_status_updated" in names
    assert "idx_validations_catalog_date" in names


def test_init_db_drops_removed_sample_columns_from_existing_database(monkeypatch, tmp_path):
    config, database = _fresh_database(monkeypatch, tmp_path)

    database.init_db()
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("ALTER TABLE clinical_samples ADD COLUMN expiration_date TEXT")
        conn.execute("ALTER TABLE clinical_samples ADD COLUMN validation_status TEXT")

    database.init_db()

    with sqlite3.connect(config.DB_PATH) as conn:
        sample_columns = {row[1] for row in conn.execute("PRAGMA table_info(clinical_samples)").fetchall()}

    assert "expiration_date" not in sample_columns
    assert "validation_status" not in sample_columns


def test_init_db_drops_removed_order_arrival_tables_and_creates_system_nodes(monkeypatch, tmp_path):
    config, database = _fresh_database(monkeypatch, tmp_path)

    database.init_db()

    with sqlite3.connect(config.DB_PATH) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        nodes = {
            row[0]: row[1]
            for row in conn.execute("SELECT id, name FROM storage_nodes WHERE id IN (-1, -2, -3, -4)").fetchall()
        }
        reagent_default = next(row for row in conn.execute("PRAGMA table_info(reagents)").fetchall() if row[1] == "storage_node_id")[4]
        sample_default = next(row for row in conn.execute("PRAGMA table_info(clinical_samples)").fetchall() if row[1] == "storage_node_id")[4]

    assert "orders" not in tables
    assert "arrivals" not in tables
    assert nodes == {-1: "未订购", -2: "未到货", -3: "未归位", -4: "已出库"}
    assert reagent_default == "-3"
    assert sample_default == "-3"


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
