from __future__ import annotations

import sqlite3

from common import now_text
from config import (
    INITIAL_ADMIN_DISPLAY_NAME,
    INITIAL_ADMIN_PASSWORD,
    INITIAL_ADMIN_USERNAME,
    IS_PRODUCTION,
    DB_PATH,
    SCHEMA_PATH,
)


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reagents_name ON reagents(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reagents_expiration ON reagents(expiration_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reagents_storage_node ON reagents(storage_node_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reagents_source ON reagents(source_code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clinical_samples_code ON clinical_samples(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clinical_samples_storage_node ON clinical_samples(storage_node_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arrivals_storage_node ON arrivals(storage_node_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_arrivals_item ON arrivals(item_type, item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_validations_catalog_no ON validations(catalog_no)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movements_object ON movements(object_type, object_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movements_from_storage_node ON movements(from_storage_node_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_movements_to_storage_node ON movements(to_storage_node_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_nodes_parent ON storage_nodes(parent_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_storage_nodes_type ON storage_nodes(node_type)")
        _ensure_inventory_search_index(conn)
        _ensure_admin_user(conn)
        _repair_storage_references(conn)
        _ensure_root_storage_node(conn)
        conn.commit()


def _ensure_inventory_search_index(conn: sqlite3.Connection) -> None:
    try:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS inventory_search_fts USING fts5(
                item_type UNINDEXED,
                item_id UNINDEXED,
                name,
                code,
                source_code,
                catalog_no,
                brand,
                category,
                amount,
                amount_unit,
                note,
                position_in_box,
                tokenize='unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS reagents_ai_fts AFTER INSERT ON reagents BEGIN
                INSERT INTO inventory_search_fts(
                    rowid, item_type, item_id, name, code, source_code, catalog_no, brand,
                    category, amount, amount_unit, note, position_in_box
                )
                VALUES (
                    NEW.id, 'reagent', NEW.id, NEW.name, NEW.code, NEW.source_code, NEW.catalog_no, NEW.brand,
                    NEW.category, NEW.amount, NEW.amount_unit, NEW.note, NEW.position_in_box
                );
            END;

            CREATE TRIGGER IF NOT EXISTS reagents_ad_fts AFTER DELETE ON reagents BEGIN
                DELETE FROM inventory_search_fts WHERE rowid = OLD.id;
            END;

            CREATE TRIGGER IF NOT EXISTS reagents_au_fts AFTER UPDATE ON reagents BEGIN
                DELETE FROM inventory_search_fts WHERE rowid = OLD.id;
                INSERT INTO inventory_search_fts(
                    rowid, item_type, item_id, name, code, source_code, catalog_no, brand,
                    category, amount, amount_unit, note, position_in_box
                )
                VALUES (
                    NEW.id, 'reagent', NEW.id, NEW.name, NEW.code, NEW.source_code, NEW.catalog_no, NEW.brand,
                    NEW.category, NEW.amount, NEW.amount_unit, NEW.note, NEW.position_in_box
                );
            END;

            CREATE TRIGGER IF NOT EXISTS clinical_samples_ai_fts AFTER INSERT ON clinical_samples BEGIN
                INSERT INTO inventory_search_fts(
                    rowid, item_type, item_id, name, code, source_code, catalog_no, brand,
                    category, amount, amount_unit, note, position_in_box
                )
                VALUES (
                    1000000000 + NEW.id, 'sample', NEW.id, NEW.name, NEW.code, NEW.source_code, '', '',
                    NEW.category, NEW.amount, NEW.amount_unit, NEW.note, NEW.position_in_box
                );
            END;

            CREATE TRIGGER IF NOT EXISTS clinical_samples_ad_fts AFTER DELETE ON clinical_samples BEGIN
                DELETE FROM inventory_search_fts WHERE rowid = 1000000000 + OLD.id;
            END;

            CREATE TRIGGER IF NOT EXISTS clinical_samples_au_fts AFTER UPDATE ON clinical_samples BEGIN
                DELETE FROM inventory_search_fts WHERE rowid = 1000000000 + OLD.id;
                INSERT INTO inventory_search_fts(
                    rowid, item_type, item_id, name, code, source_code, catalog_no, brand,
                    category, amount, amount_unit, note, position_in_box
                )
                VALUES (
                    1000000000 + NEW.id, 'sample', NEW.id, NEW.name, NEW.code, NEW.source_code, '', '',
                    NEW.category, NEW.amount, NEW.amount_unit, NEW.note, NEW.position_in_box
                );
            END;
            """
        )
        _rebuild_inventory_search_index(conn)
    except sqlite3.Error:
        conn.execute("DROP TABLE IF EXISTS inventory_search_fts")


def _rebuild_inventory_search_index(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM inventory_search_fts")
    conn.execute(
        """
        INSERT INTO inventory_search_fts(
            rowid, item_type, item_id, name, code, source_code, catalog_no, brand,
            category, amount, amount_unit, note, position_in_box
        )
        SELECT id, 'reagent', id, name, code, source_code, catalog_no, brand,
               category, amount, amount_unit, note, position_in_box
        FROM reagents
        """
    )
    conn.execute(
        """
        INSERT INTO inventory_search_fts(
            rowid, item_type, item_id, name, code, source_code, catalog_no, brand,
            category, amount, amount_unit, note, position_in_box
        )
        SELECT 1000000000 + id, 'sample', id, name, code, source_code, '', '',
               category, amount, amount_unit, note, position_in_box
        FROM clinical_samples
        """
    )


def _ensure_admin_user(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if existing is not None:
        return
    if IS_PRODUCTION:
        insecure_passwords = {"", "admin123", "change-this-admin-password"}
        if INITIAL_ADMIN_PASSWORD in insecure_passwords:
            raise RuntimeError("生产环境首次初始化必须设置安全的 LABKEEPER_INITIAL_ADMIN_PASSWORD")
    elif not INITIAL_ADMIN_PASSWORD:
        raise RuntimeError("首次初始化必须设置 LABKEEPER_INITIAL_ADMIN_PASSWORD")
    from auth import hash_password

    timestamp = now_text()
    conn.execute(
        """
        INSERT INTO users (username, display_name, password_hash, role, is_active, created_at, updated_at)
        VALUES (?, ?, ?, 'admin', 1, ?, ?)
        """,
        (
            INITIAL_ADMIN_USERNAME.strip() or "admin",
            INITIAL_ADMIN_DISPLAY_NAME.strip() or (INITIAL_ADMIN_USERNAME.strip() or "admin"),
            hash_password(INITIAL_ADMIN_PASSWORD),
            timestamp,
            timestamp,
        ),
    )


def _ensure_root_storage_node(conn: sqlite3.Connection) -> None:
    root = conn.execute(
        """
        SELECT id FROM storage_nodes
        WHERE parent_id IS NULL
        ORDER BY id LIMIT 1
        """
    ).fetchone()
    if root is not None:
        return
    admin = conn.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
    admin_id = admin["id"] if admin else None
    timestamp = now_text()
    conn.execute(
        """
        INSERT INTO storage_nodes
            (id, parent_id, name, node_type, location_code, rows, cols, grid_row, grid_col, note, sort_order,
             created_by, updated_by, created_at, updated_at)
        VALUES (1, NULL, '研究所', 'space', '研究所', NULL, NULL, NULL, NULL, '默认根节点', 0, ?, ?, ?, ?)
        """,
        (admin_id, admin_id, timestamp, timestamp),
    )


def _repair_storage_references(conn: sqlite3.Connection) -> None:
    for table in ("reagents", "clinical_samples", "arrivals"):
        conn.execute(
            f"""
            UPDATE {table}
            SET storage_node_id = NULL, position_in_box = NULL
            WHERE storage_node_id IS NOT NULL
              AND storage_node_id NOT IN (SELECT id FROM storage_nodes)
            """
        )
    for column in ("from_storage_node_id", "to_storage_node_id"):
        conn.execute(
            f"""
            UPDATE movements
            SET {column} = NULL
            WHERE {column} IS NOT NULL
              AND {column} NOT IN (SELECT id FROM storage_nodes)
            """
        )
