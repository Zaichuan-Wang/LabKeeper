from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
DEMO_DB_PATH = ROOT / "dev_tools" / "demo.sqlite3"

sys.path.insert(0, str(BACKEND))

from auth import hash_password  # noqa: E402


def main() -> None:
    remove_sqlite_files(DEMO_DB_PATH)
    DEMO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DEMO_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        seed(conn)
        assert_integrity(conn)
    print(f"Demo database written: {DEMO_DB_PATH}")


def remove_sqlite_files(path: Path) -> None:
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists():
            candidate.unlink()


def seed(conn: sqlite3.Connection) -> None:
    now = "2026-06-13 09:00:00"
    conn.execute(
        """
        INSERT INTO users (id, username, display_name, password_hash, role, permissions, is_active, created_at, updated_at)
        VALUES (1, 'admin', '管理员', ?, 'admin', NULL, 1, ?, ?)
        """,
        (hash_password("admin123"), now, now),
    )
    conn.execute(
        """
        INSERT INTO users (id, username, display_name, password_hash, role, permissions, is_active, created_at, updated_at)
        VALUES (2, 'demo_user', '测试用户', ?, 'user', ?, 1, ?, ?)
        """,
        (hash_password("demo123"), '{"inventory.manage":true,"location.manage":false,"inventory.search":true}', now, now),
    )
    conn.executemany(
        """
        INSERT INTO storage_nodes
            (id, parent_id, name, node_type, location_code, rows, cols, grid_row, grid_col, note, sort_order,
             created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        [
            (1, None, "研究所", "space", "LAB", 1, 1, None, None, "Demo 根空间", 0, now, now),
            (2, 1, "负80冰箱A", "space", "FZ-A", 2, 2, None, None, "低温样本和抗体", 10, now, now),
            (3, 2, "第一层抽屉", "space", "FZ-A-D1", 1, 3, 1, 1, "", 10, now, now),
            (4, 3, "抗体盒-001", "box", "AB-001", 9, 9, 1, 1, "", 10, now, now),
            (5, 3, "样本盒-001", "box", "SMP-001", 9, 9, 1, 2, "", 20, now, now),
            (6, 1, "4度冰箱", "space", "FRIDGE-4C", 1, 2, None, None, "短期试剂", 20, now, now),
        ],
    )
    conn.executemany(
        """
        INSERT INTO reagents
            (id, code, source_code, aliquot_no, name, category, brand, catalog_no, amount, amount_unit, quantity,
             status, storage_node_id, position_in_box, entry_date, expiration_date, validation_status, note,
             created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        [
            (1, "RG000001", "RG000001", None, "Anti-CD45 抗体", "抗体", "BioLegend", "103101", 100, "uL", 1, "可用", 4, "A1", "2026-05-20", "2027-05-20", "通过", "Demo 验证通过抗体", now, now),
            (2, "RG000002", "RG000002", None, "PBS 缓冲液", "缓冲液", "Thermo Fisher", "10010023", 500, "mL", 1, "可用", 6, "A1", "2026-06-01", "2026-09-01", "未验证", "短期存放", now, now),
            (3, "RG000003", "RG000003", None, "ELISA 试剂盒", "试剂盒", "R&D Systems", "DY210", 1, "kit", 1, "停用", None, None, "2026-01-12", "2026-07-12", "待复核", "停用但仍保留实物记录", now, now),
        ],
    )
    conn.executemany(
        """
        INSERT INTO clinical_samples
            (id, code, source_code, aliquot_no, name, category, amount, amount_unit, quantity, status,
             storage_node_id, position_in_box, entry_date, expiration_date, validation_status, note,
             created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        [
            (1, "SP000001", "SP000001", 1, "SMP-001", "血清", 200, "uL", 1, "可用", 5, "A1", "2026-06-02", None, "", "Demo 标本 1", now, now),
            (2, "SP000002", "SP000001", 2, "SMP-001", "血清", 200, "uL", 1, "可用", 5, "A2", "2026-06-02", None, "", "Demo 标本 1 分装", now, now),
            (3, "SP000003", "SP000003", 1, "SMP-002", "灌洗液", 500, "uL", 1, "停用", None, None, "2026-06-05", None, "", "未归位示例", now, now),
        ],
    )
    conn.executemany(
        """
        INSERT INTO orders
            (id, requester_id, name, category, brand, catalog_no, amount, amount_unit, quantity, reason, price, status, created_at, updated_at)
        VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, "Anti-CD45 抗体", "抗体", "BioLegend", "103101", 100, "uL", 1, "流式实验", 1800, "已订购", "2026-05-18 09:00:00", now),
            (2, "二抗 HRP", "抗体", "CST", "7074", 100, "uL", 1, "WB 补货", 1200, "已订购", "2026-06-10 10:30:00", now),
        ],
    )
    conn.execute(
        """
        INSERT INTO arrivals
            (id, order_id, item_type, item_id, entry_date, received_by, storage_node_id, position_in_box,
             location_snapshot, expiration_date, note, created_at)
        VALUES (1, 1, 'reagent', 1, '2026-05-20', 1, 4, 'A1', '研究所 / 负80冰箱A / 第一层抽屉 / 抗体盒-001 / A1', '2027-05-20', 'Demo 到货', ?)
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT INTO validations
            (id, catalog_no, validator_id, validation_date, method, result, description, image_path, created_at)
        VALUES (1, '103101', 1, '2026-05-21', '流式', '通过', 'Demo 验证记录', '', ?)
        """,
        (now,),
    )
    conn.executemany(
        """
        INSERT INTO movements
            (id, object_type, object_id, item_type, item_id, from_storage_node_id, from_position_in_box,
             to_storage_node_id, to_position_in_box, from_location_snapshot, to_location_snapshot, moved_by, moved_at, reason, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        [
            (1, "reagent", "1", "reagent", 1, None, None, 4, "A1", "未归位", "研究所 / 负80冰箱A / 第一层抽屉 / 抗体盒-001 / A1", now, "Demo 入库", ""),
            (2, "sample", "1", "sample", 1, None, None, 5, "A1", "未归位", "研究所 / 负80冰箱A / 第一层抽屉 / 样本盒-001 / A1", now, "Demo 入库", ""),
        ],
    )
    conn.execute(
        """
        INSERT INTO audit_logs (user_id, action, target_table, target_id, new_value, created_at)
        VALUES (1, 'dev_seed_demo_database', 'database', NULL, '{"source":"dev_tools/build_demo_db.py"}', ?)
        """,
        (now,),
    )
    conn.commit()


def assert_integrity(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    if not row or row[0] != "ok":
        raise RuntimeError("Demo database integrity check failed")


if __name__ == "__main__":
    main()
