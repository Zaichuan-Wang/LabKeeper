from __future__ import annotations

import sqlite3

from core.common import get_logger, now_text
from core.config import (
    INITIAL_ADMIN_DISPLAY_NAME,
    INITIAL_ADMIN_PASSWORD,
    INITIAL_ADMIN_USERNAME,
    IS_PRODUCTION,
    DB_PATH,
    SCHEMA_PATH,
)

logger = get_logger("lab.database")

LIGHTWEIGHT_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_reagents_expiration ON reagents(expiration_date)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_updated ON reagents(updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_status_updated ON reagents(status, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_category_updated ON reagents(category, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_validation_updated ON reagents(validation_status, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_storage_status_updated ON reagents(storage_node_id, status, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_storage_position_status ON reagents(storage_node_id, grid_cell, status)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_catalog_updated ON reagents(catalog_no, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_source_aliquot ON reagents(COALESCE(source_code, code, id), aliquot_no)",
    "CREATE INDEX IF NOT EXISTS idx_clinical_samples_code ON clinical_samples(code)",
    "CREATE INDEX IF NOT EXISTS idx_clinical_samples_updated ON clinical_samples(updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_clinical_samples_status_updated ON clinical_samples(status, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_clinical_samples_name_updated ON clinical_samples(name, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_clinical_samples_category_updated ON clinical_samples(category, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_clinical_samples_storage_status_updated ON clinical_samples(storage_node_id, status, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_clinical_samples_storage_position_status ON clinical_samples(storage_node_id, grid_cell, status)",
    "CREATE INDEX IF NOT EXISTS idx_clinical_samples_source_aliquot ON clinical_samples(COALESCE(source_code, code, id), aliquot_no)",
    "CREATE INDEX IF NOT EXISTS idx_arrivals_storage_node ON arrivals(storage_node_id)",
    "CREATE INDEX IF NOT EXISTS idx_arrivals_item_created ON arrivals(item_type, item_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_arrivals_order ON arrivals(order_id)",
    "CREATE INDEX IF NOT EXISTS idx_arrivals_created ON arrivals(created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_validations_catalog_date ON validations(catalog_no, validation_date DESC, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_validations_created ON validations(created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_orders_status_updated ON orders(status, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_orders_updated ON orders(updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_movements_item_moved ON movements(item_type, item_id, moved_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_movements_from_storage_node ON movements(from_storage_node_id)",
    "CREATE INDEX IF NOT EXISTS idx_movements_to_storage_node ON movements(to_storage_node_id)",
    "CREATE INDEX IF NOT EXISTS idx_movements_moved ON movements(moved_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_movements_checkout_moved ON movements(moved_at DESC, id DESC) WHERE to_location_snapshot = '已出库'",
    "CREATE INDEX IF NOT EXISTS idx_storage_nodes_parent_sort_name ON storage_nodes(parent_id, sort_order, name)",
    "CREATE INDEX IF NOT EXISTS idx_storage_nodes_parent_grid ON storage_nodes(parent_id, grid_row, grid_col)",
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_target_created ON audit_logs(target_table, target_id, created_at DESC)",
)

OBSOLETE_INDEX_NAMES = (
    "idx_reagents_name",
    "idx_reagents_storage_node",
    "idx_reagents_source",
    "idx_clinical_samples_storage_node",
    "idx_arrivals_item",
    "idx_validations_catalog_no",
    "idx_orders_status",
    "idx_movements_object",
    "idx_movements_to_snapshot_moved",
    "idx_storage_nodes_parent",
    "idx_audit_logs_created",
)

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA wal_autocheckpoint = 200")
    conn.execute("PRAGMA journal_size_limit = 1048576")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        _apply_base_schema(conn)
        _ensure_indexes(conn)
        _ensure_admin_user(conn)
        _ensure_root_storage_node(conn)
        _repair_known_inconsistencies(conn)
        conn.commit()
    finally:
        conn.close()


def _apply_base_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    _drop_obsolete_indexes(conn)
    for sql in LIGHTWEIGHT_INDEX_SQL:
        conn.execute(sql)


def _drop_obsolete_indexes(conn: sqlite3.Connection) -> None:
    for index_name in OBSOLETE_INDEX_NAMES:
        conn.execute(f'DROP INDEX IF EXISTS "{index_name}"')


def compact_database() -> dict[str, int]:
    init_db()
    before = _sqlite_file_size()
    conn = connect()
    try:
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.execute("PRAGMA optimize")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    after = _sqlite_file_size()
    return {"before_bytes": before, "after_bytes": after, "saved_bytes": max(0, before - after)}


def _sqlite_file_size() -> int:
    total = 0
    for path in (DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal"), DB_PATH.with_name(DB_PATH.name + "-shm")):
        if path.exists():
            total += path.stat().st_size
    return total


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
    from services.auth import hash_password

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
            (id, parent_id, name, node_type, space_type, location_code, rows, cols, grid_row, grid_col, note, sort_order,
             created_by, updated_by, created_at, updated_at)
        VALUES (1, NULL, '研究所', 'space', 5, '研究所', NULL, NULL, NULL, NULL, '默认根节点', 0, ?, ?, ?, ?)
        """,
        (admin_id, admin_id, timestamp, timestamp),
    )


def _repair_known_inconsistencies(conn: sqlite3.Connection) -> None:
    _repair_storage_references(conn)


def _repair_storage_references(conn: sqlite3.Connection) -> None:
    for table in ("reagents", "clinical_samples", "arrivals"):
        cursor = conn.execute(
            f"""
            UPDATE {table}
            SET storage_node_id = NULL, grid_cell = NULL
            WHERE storage_node_id IS NOT NULL
              AND storage_node_id NOT IN (SELECT id FROM storage_nodes)
            """
        )
        if cursor.rowcount:
            logger.warning("已清理 %s 条 %s 的无效存放位置引用", cursor.rowcount, table)
    for column in ("from_storage_node_id", "to_storage_node_id"):
        cursor = conn.execute(
            f"""
            UPDATE movements
            SET {column} = NULL
            WHERE {column} IS NOT NULL
              AND {column} NOT IN (SELECT id FROM storage_nodes)
            """
        )
        if cursor.rowcount:
            logger.warning("已清理 %s 条 movements.%s 的无效位置引用", cursor.rowcount, column)
