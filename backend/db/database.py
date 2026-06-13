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

SCHEMA_VERSION = 1


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
        _apply_base_schema(conn)
        _apply_migrations(conn)
        _ensure_indexes(conn)
        _ensure_inventory_search_index(conn)
        _ensure_admin_user(conn)
        _ensure_root_storage_node(conn)
        _repair_known_inconsistencies(conn)
        conn.commit()


def _apply_base_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def _apply_migrations(conn: sqlite3.Connection) -> None:
    _ensure_schema_migrations_table(conn)
    current_version = _schema_version(conn)
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(f"数据库 schema 版本 {current_version} 高于当前程序支持的版本 {SCHEMA_VERSION}")
    _sync_table_columns(conn)
    if current_version < SCHEMA_VERSION:
        _set_schema_version(conn, SCHEMA_VERSION)
        logger.info("数据库 schema 版本已更新到 %s", SCHEMA_VERSION)


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    return int(row["version"] or 0)


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, now_text()),
    )


def _sync_table_columns(conn: sqlite3.Connection) -> None:
    expected = _schema_table_columns()
    for table, columns in expected.items():
        existing = _table_column_names(conn, table)
        if not existing:
            continue
        for column_name, column_sql in columns.items():
            if column_name in existing:
                continue
            if _is_add_column_safe(column_sql):
                conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {column_sql}')
                logger.info("数据库自动补齐字段：%s.%s", table, column_name)
            else:
                logger.warning("数据库缺少字段但不能自动补齐：%s.%s", table, column_name)


def _schema_table_columns() -> dict[str, dict[str, str]]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        tables = [
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {table: _table_column_sql(conn, table) for table in tables}
    finally:
        conn.close()


def _table_column_sql(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    result: dict[str, str] = {}
    for row in rows:
        parts = [f'"{row["name"]}"', str(row["type"] or "").strip()]
        if int(row["notnull"]) == 1:
            parts.append("NOT NULL")
        if row["dflt_value"] is not None:
            parts.append(f'DEFAULT {row["dflt_value"]}')
        if int(row["pk"]) > 0:
            continue
        result[str(row["name"])] = " ".join(part for part in parts if part)
    return result


def _table_column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}


def _is_add_column_safe(column_sql: str) -> bool:
    upper = column_sql.upper()
    if "PRIMARY KEY" in upper or "UNIQUE" in upper or "REFERENCES" in upper:
        return False
    if "NOT NULL" in upper and "DEFAULT" not in upper:
        return False
    return True


def _ensure_indexes(conn: sqlite3.Connection) -> None:
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
    except sqlite3.Error as exc:
        logger.warning("库存全文搜索索引不可用，已跳过 FTS 初始化：%s", exc)
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
            (id, parent_id, name, node_type, location_code, rows, cols, grid_row, grid_col, note, sort_order,
             created_by, updated_by, created_at, updated_at)
        VALUES (1, NULL, '研究所', 'space', '研究所', NULL, NULL, NULL, NULL, '默认根节点', 0, ?, ?, ?, ?)
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
            SET storage_node_id = NULL, position_in_box = NULL
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
