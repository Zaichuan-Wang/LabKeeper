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
from core.constants import (
    SYSTEM_CHECKED_OUT_NODE_ID,
    SYSTEM_NOT_ARRIVED_NODE_ID,
    SYSTEM_NOT_ORDERED_NODE_ID,
    SYSTEM_STORAGE_NODE_LABELS,
    SYSTEM_UNPLACED_NODE_ID,
)

logger = get_logger("lab.database")

LIGHTWEIGHT_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_reagents_expiration ON reagents(expiration_date)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_updated ON reagents(updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_status_updated ON reagents(status, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_reagents_category_updated ON reagents(category, updated_at DESC, id DESC)",
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
    "CREATE INDEX IF NOT EXISTS idx_validations_catalog_date ON validations(catalog_no, validation_date DESC, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_validations_created ON validations(created_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_movements_item_moved ON movements(item_type, item_id, moved_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_movements_reason_moved ON movements(reason, moved_at DESC, id DESC)",
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
    "idx_reagents_validation_updated",
    "idx_reagents_storage_node",
    "idx_reagents_source",
    "idx_clinical_samples_storage_node",
    "idx_arrivals_item",
    "idx_arrivals_storage_node",
    "idx_arrivals_order",
    "idx_arrivals_created",
    "idx_validations_catalog_no",
    "idx_orders_status",
    "idx_orders_status_updated",
    "idx_orders_updated",
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
        _ensure_system_storage_nodes(conn)
        _ensure_admin_user(conn)
        _ensure_root_storage_node(conn)
        _repair_known_inconsistencies(conn)
        conn.commit()
    finally:
        conn.close()


def _apply_base_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    _drop_removed_business_tables(conn)
    _drop_obsolete_indexes(conn)
    _drop_removed_reagent_columns(conn)
    _drop_removed_sample_columns(conn)
    for sql in LIGHTWEIGHT_INDEX_SQL:
        conn.execute(sql)


def _drop_removed_business_tables(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS arrivals")
    conn.execute("DROP TABLE IF EXISTS orders")


def _drop_obsolete_indexes(conn: sqlite3.Connection) -> None:
    for index_name in OBSOLETE_INDEX_NAMES:
        conn.execute(f'DROP INDEX IF EXISTS "{index_name}"')


def _drop_removed_reagent_columns(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "reagents", "validation_status"):
        return
    try:
        conn.execute("ALTER TABLE reagents DROP COLUMN validation_status")
    except sqlite3.OperationalError:
        logger.warning("当前 SQLite 不支持删除旧列 reagents.validation_status，代码将忽略该闲置列。")


def _drop_removed_sample_columns(conn: sqlite3.Connection) -> None:
    for column in ("expiration_date", "validation_status"):
        if not _column_exists(conn, "clinical_samples", column):
            continue
        try:
            conn.execute(f"ALTER TABLE clinical_samples DROP COLUMN {column}")
        except sqlite3.OperationalError:
            logger.warning("当前 SQLite 不支持删除旧列 clinical_samples.%s，代码将忽略该闲置列。", column)


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


def _ensure_system_storage_nodes(conn: sqlite3.Connection) -> None:
    timestamp = now_text()
    rows = (
        (SYSTEM_NOT_ORDERED_NODE_ID, SYSTEM_STORAGE_NODE_LABELS[SYSTEM_NOT_ORDERED_NODE_ID], -100),
        (SYSTEM_NOT_ARRIVED_NODE_ID, SYSTEM_STORAGE_NODE_LABELS[SYSTEM_NOT_ARRIVED_NODE_ID], -99),
        (SYSTEM_UNPLACED_NODE_ID, SYSTEM_STORAGE_NODE_LABELS[SYSTEM_UNPLACED_NODE_ID], -98),
        (SYSTEM_CHECKED_OUT_NODE_ID, SYSTEM_STORAGE_NODE_LABELS[SYSTEM_CHECKED_OUT_NODE_ID], -97),
    )
    for node_id, label, sort_order in rows:
        conn.execute(
            """
            INSERT INTO storage_nodes
                (id, parent_id, name, node_type, space_type, location_code, rows, cols, grid_row, grid_col,
                 note, sort_order, created_by, updated_by, created_at, updated_at)
            VALUES (?, NULL, ?, 'system', 5, ?, NULL, NULL, NULL, NULL,
                    '系统状态节点', ?, NULL, NULL, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                node_type = 'system',
                location_code = excluded.location_code,
                note = excluded.note,
                sort_order = excluded.sort_order,
                updated_at = excluded.updated_at
            """,
            (node_id, label, label, sort_order, timestamp, timestamp),
        )


def _ensure_root_storage_node(conn: sqlite3.Connection) -> None:
    root = conn.execute(
        """
        SELECT id FROM storage_nodes
        WHERE parent_id IS NULL AND id > 0 AND COALESCE(node_type, 'space') != 'system'
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
    _ensure_reagent_price_column(conn)
    _repair_storage_references(conn)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """检查表中的列是否存在"""
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(col["name"] == column for col in cols)


def _ensure_reagent_price_column(conn: sqlite3.Connection) -> None:
    price_column_added = not _column_exists(conn, "reagents", "price")
    if price_column_added:
        conn.execute("ALTER TABLE reagents ADD COLUMN price REAL")


def _repair_storage_references(conn: sqlite3.Connection) -> None:
    for table in ("reagents", "clinical_samples"):
        has_grid_cell = _column_exists(conn, table, "grid_cell")
        set_clause = f"storage_node_id = {SYSTEM_UNPLACED_NODE_ID}, grid_cell = NULL" if has_grid_cell else f"storage_node_id = {SYSTEM_UNPLACED_NODE_ID}"
        cursor = conn.execute(
            f"""
            UPDATE {table}
            SET {set_clause}
            WHERE storage_node_id IS NULL
               OR storage_node_id NOT IN (SELECT id FROM storage_nodes)
            """
        )
        if cursor.rowcount:
            logger.warning("已清理 %s 条 %s 的无效存放位置引用", cursor.rowcount, table)
    for column in ("from_storage_node_id", "to_storage_node_id"):
        cursor = conn.execute(
            f"""
            UPDATE movements
            SET {column} = {SYSTEM_UNPLACED_NODE_ID}
            WHERE {column} IS NOT NULL
              AND {column} NOT IN (SELECT id FROM storage_nodes)
            """
        )
        if cursor.rowcount:
            logger.warning("已清理 %s 条 movements.%s 的无效位置引用", cursor.rowcount, column)
