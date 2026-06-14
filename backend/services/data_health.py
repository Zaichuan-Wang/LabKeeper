from __future__ import annotations

from typing import Any

from core.common import now_text, row_dict
from core.constants import PHYSICAL_INVENTORY_STATUS_SQL, STATUS_CONSUMED, STATUS_ORDERED
from db.database import connect
from services.storage_inventory import computed_storage_location


EXAMPLE_LIMIT = 20


def _item(key: str, label: str, severity: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "severity": severity,
        "count": len(rows),
        "examples": rows[:EXAMPLE_LIMIT],
    }


def _location(conn: Any, row: Any) -> str:
    return computed_storage_location(conn, row_dict(row) or {})


def report() -> dict[str, Any]:
    with connect() as conn:
        items = [
            _consumed_reagents_with_location(conn),
            _consumed_samples_with_location(conn),
            _ordered_reagents_with_location(conn),
            _inventory_missing_storage(conn),
            _duplicate_positions(conn),
            _duplicate_sample_aliquots(conn),
            _catalog_name_conflicts(conn),
        ]
    errors = sum(int(item["count"] or 0) for item in items if item["severity"] == "error")
    warnings = sum(int(item["count"] or 0) for item in items if item["severity"] == "warning")
    return {
        "items": items,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "checked_at": now_text(),
        },
    }


def _consumed_reagents_with_location(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id, code, name, status, storage_node_id, grid_cell
        FROM reagents
        WHERE status = ? AND (storage_node_id IS NOT NULL OR COALESCE(grid_cell, '') != '')
        ORDER BY updated_at DESC, id DESC
        LIMIT 200
        """,
        (STATUS_CONSUMED,),
    ).fetchall()
    examples = [
        {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "location": _location(conn, row),
            "message": "状态为已耗尽，但仍有存放空间或孔位。",
        }
        for row in rows
    ]
    return _item("consumed_reagent_has_location", "已耗尽试剂仍有位置记录", "error", examples)


def _consumed_samples_with_location(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id, code, name, category, status, storage_node_id, grid_cell
        FROM clinical_samples
        WHERE status = ? AND (storage_node_id IS NOT NULL OR COALESCE(grid_cell, '') != '')
        ORDER BY updated_at DESC, id DESC
        LIMIT 200
        """,
        (STATUS_CONSUMED,),
    ).fetchall()
    examples = [
        {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "category": row["category"],
            "location": _location(conn, row),
            "message": "状态为已耗尽，但仍有存放空间或孔位。",
        }
        for row in rows
    ]
    return _item("consumed_sample_has_location", "已耗尽标本仍有位置记录", "error", examples)


def _ordered_reagents_with_location(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id, code, name, status, storage_node_id, grid_cell
        FROM reagents
        WHERE status = ? AND (storage_node_id IS NOT NULL OR COALESCE(grid_cell, '') != '')
        ORDER BY updated_at DESC, id DESC
        LIMIT 200
        """,
        (STATUS_ORDERED,),
    ).fetchall()
    examples = [
        {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "location": _location(conn, row),
            "message": "状态为已订购，理论上还未形成实物库存。",
        }
        for row in rows
    ]
    return _item("ordered_reagent_has_location", "已订购试剂仍有位置记录", "error", examples)


def _inventory_missing_storage(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        f"""
        SELECT 'reagent' AS item_type, id, code, name, status, storage_node_id, grid_cell
        FROM reagents
        WHERE status IN {PHYSICAL_INVENTORY_STATUS_SQL} AND storage_node_id IS NOT NULL
          AND storage_node_id NOT IN (SELECT id FROM storage_nodes)
        UNION ALL
        SELECT 'sample' AS item_type, id, code, name, status, storage_node_id, grid_cell
        FROM clinical_samples
        WHERE status IN {PHYSICAL_INVENTORY_STATUS_SQL} AND storage_node_id IS NOT NULL
          AND storage_node_id NOT IN (SELECT id FROM storage_nodes)
        LIMIT 200
        """
    ).fetchall()
    examples = [
        {
            "item_type": row["item_type"],
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "storage_node_id": row["storage_node_id"],
            "message": "库存指向的空间不存在。",
        }
        for row in rows
    ]
    return _item("inventory_missing_storage", "库存指向不存在的空间", "error", examples)


def _duplicate_positions(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        f"""
        SELECT storage_node_id, grid_cell, COUNT(*) AS n,
               GROUP_CONCAT(item_type || ':' || code || ' · ' || name, '；') AS objects
        FROM (
            SELECT '试剂' AS item_type, code, name, storage_node_id, grid_cell
            FROM reagents
            WHERE storage_node_id IS NOT NULL AND COALESCE(grid_cell, '') != '' AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}
            UNION ALL
            SELECT '标本' AS item_type, code, name, storage_node_id, grid_cell
            FROM clinical_samples
            WHERE storage_node_id IS NOT NULL AND COALESCE(grid_cell, '') != '' AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}
        )
        GROUP BY storage_node_id, grid_cell
        HAVING COUNT(*) > 1
        ORDER BY n DESC
        LIMIT 200
        """
    ).fetchall()
    examples = []
    for row in rows:
        node = conn.execute("SELECT * FROM storage_nodes WHERE id = ?", (row["storage_node_id"],)).fetchone()
        node_name = node["name"] if node else f"空间 {row['storage_node_id']}"
        examples.append({
            "storage_node_id": row["storage_node_id"],
            "grid_cell": row["grid_cell"],
            "count": row["n"],
            "objects": row["objects"],
            "message": f"{node_name} 的 {row['grid_cell']} 被多个库存对象占用。",
        })
    return _item("duplicate_storage_position", "同一孔位被多个库存对象占用", "error", examples)


def _duplicate_sample_aliquots(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT COALESCE(source_code, code) AS source_code, aliquot_no, COUNT(*) AS n,
               GROUP_CONCAT(id || ':' || code || ' · ' || name || ' · ' || COALESCE(category, ''), '；') AS objects
        FROM clinical_samples
        WHERE COALESCE(source_code, code, '') != '' AND aliquot_no IS NOT NULL
        GROUP BY COALESCE(source_code, code), aliquot_no
        HAVING COUNT(*) > 1
        ORDER BY n DESC, source_code
        LIMIT 200
        """
    ).fetchall()
    examples = [
        {
            "source_code": row["source_code"],
            "aliquot_no": row["aliquot_no"],
            "count": row["n"],
            "objects": row["objects"],
            "message": "同一来源标本下出现了重复管号。",
        }
        for row in rows
    ]
    return _item("duplicate_sample_aliquot", "标本来源编号 + 管号重复", "error", examples)


def _catalog_name_conflicts(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT catalog_no, COUNT(DISTINCT TRIM(COALESCE(name, ''))) AS name_count,
               GROUP_CONCAT(DISTINCT TRIM(COALESCE(name, ''))) AS names
        FROM reagents
        WHERE COALESCE(catalog_no, '') != ''
        GROUP BY catalog_no
        HAVING COUNT(DISTINCT TRIM(COALESCE(name, ''))) > 1
        ORDER BY name_count DESC, catalog_no
        LIMIT 200
        """
    ).fetchall()
    examples = [
        {
            "catalog_no": row["catalog_no"],
            "name_count": row["name_count"],
            "names": row["names"],
            "message": "同一货号对应多个名称，请确认是否为录入不一致。",
        }
        for row in rows
    ]
    return _item("catalog_name_conflict", "同一货号对应多个名称", "warning", examples)
