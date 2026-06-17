from __future__ import annotations

import sqlite3
from typing import Any

from core.common import ApiError, now_text, row_dict, safe_float
from core.constants import (
    MOVEMENT_REASON_STATUS,
    PHYSICAL_INVENTORY_STATUSES,
    PHYSICAL_INVENTORY_STATUS_SQL,
    SYSTEM_CHECKED_OUT_NODE_ID,
    SYSTEM_NOT_ARRIVED_NODE_ID,
    SYSTEM_STORAGE_NODE_IDS,
    SYSTEM_STORAGE_NODE_LABELS,
    SYSTEM_UNPLACED_NODE_ID,
    STATUS_CONSUMED,
    STATUS_DISABLED,
    STATUS_ORDERED,
    VALIDATION_UNVERIFIED,
)

INVENTORY_TABLES = {
    "reagent": "reagents",
    "sample": "clinical_samples",
}

VALIDATION_STATUS_SQL = """
COALESCE((
    SELECT v.result
    FROM validations v
    WHERE v.catalog_no = {alias}.catalog_no
      AND COALESCE(v.catalog_no, '') != ''
    ORDER BY
      CASE v.result
        WHEN '通过' THEN 1
        WHEN '不通过' THEN 2
        WHEN '待复核' THEN 3
        WHEN '未验证' THEN 5
        ELSE 4
      END,
      v.validation_date DESC,
      v.created_at DESC,
      v.id DESC
    LIMIT 1
), '未验证')
"""


def reagent_validation_status_sql(reagent_alias: str = "reagents") -> str:
    return VALIDATION_STATUS_SQL.format(alias=reagent_alias)


def reagent_validation_statuses_by_catalogs(conn: sqlite3.Connection, catalog_numbers: list[str]) -> dict[str, str]:
    catalogs = sorted({str(catalog or "").strip() for catalog in catalog_numbers if str(catalog or "").strip()})
    statuses = {catalog: VALIDATION_UNVERIFIED for catalog in catalogs}
    if not catalogs:
        return statuses
    placeholders = ",".join("?" for _ in catalogs)
    rows = conn.execute(
        f"""
        SELECT catalog_no, result
        FROM validations
        WHERE catalog_no IN ({placeholders})
        ORDER BY
          catalog_no,
          CASE result
            WHEN '通过' THEN 1
            WHEN '不通过' THEN 2
            WHEN '待复核' THEN 3
            WHEN '未验证' THEN 5
            ELSE 4
          END,
          validation_date DESC,
          created_at DESC,
          id DESC
        """,
        catalogs,
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        catalog = str(row["catalog_no"] or "").strip()
        if not catalog or catalog in seen:
            continue
        statuses[catalog] = str(row["result"] or "").strip() or VALIDATION_UNVERIFIED
        seen.add(catalog)
    return statuses


def attach_reagent_validation_statuses(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reagent_items = [item for item in items if item.get("item_type") == "reagent"]
    catalogs = [str(item.get("catalog_no") or "").strip() for item in reagent_items]
    statuses = reagent_validation_statuses_by_catalogs(conn, catalogs)
    for item in reagent_items:
        catalog = str(item.get("catalog_no") or "").strip()
        item["validation_status"] = statuses.get(catalog, VALIDATION_UNVERIFIED)
    return items


def occupies_storage(status: str | None) -> bool:
    return str(status or "").strip() in PHYSICAL_INVENTORY_STATUSES


def _visible_inventory_types(visible_types: set[str] | None = None) -> set[str]:
    if visible_types is None:
        return set(INVENTORY_TABLES)
    return {item_type for item_type in visible_types if item_type in INVENTORY_TABLES}


def is_system_storage_node_id(node_id: Any) -> bool:
    try:
        return int(node_id) in SYSTEM_STORAGE_NODE_IDS
    except (TypeError, ValueError):
        return False


def system_storage_label(node_id: Any) -> str:
    try:
        return SYSTEM_STORAGE_NODE_LABELS.get(int(node_id), "")
    except (TypeError, ValueError):
        return ""


def default_storage_node_for_status(status: str | None) -> int:
    clean_status = str(status or "").strip()
    if clean_status == STATUS_ORDERED:
        return SYSTEM_NOT_ARRIVED_NODE_ID
    if clean_status == STATUS_CONSUMED:
        return SYSTEM_CHECKED_OUT_NODE_ID
    return SYSTEM_UNPLACED_NODE_ID


def storage_target_or_default(node_id: Any, status: str | None = None) -> int:
    if node_id in (None, ""):
        return default_storage_node_for_status(status)
    try:
        return int(node_id)
    except (TypeError, ValueError):
        return default_storage_node_for_status(status)


def grid_label(index: int, cols: int | None = None) -> str:
    if cols and cols > 0:
        row = (index - 1) // cols
        col = (index - 1) % cols + 1
        return f"{chr(ord('A') + row)}{col}" if row < 26 else str(index)
    return str(index)


def grid_position(row: int | None, col: int | None, cols: int | None, fallback: int) -> int:
    if row and col and cols and cols > 0:
        return max(1, (int(row) - 1) * int(cols) + int(col))
    return fallback


def assign_grid_positions(items: list[dict[str, Any]], cols: int) -> int:
    used: set[int] = set()
    max_position = 0
    for fallback, item in enumerate(items, start=1):
        has_manual_position = bool(item.get("grid_row") and item.get("grid_col"))
        position = grid_position(item.get("grid_row"), item.get("grid_col"), cols, fallback) if has_manual_position else fallback
        while position in used:
            position += 1
        used.add(position)
        item["grid_position"] = position
        item["grid_label"] = grid_label(position, cols)
        max_position = max(max_position, position)
    return max_position


def default_grid_for_node(rows: int | None, cols: int | None) -> tuple[int, int]:
    if rows and cols:
        return int(rows), int(cols)
    return int(rows or 1), int(cols or 1)


def clean_positive_int(value: Any, maximum: int = 50) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return min(number, maximum)


def position_options_for_node(node: sqlite3.Row | dict[str, Any] | None) -> list[str]:
    if node is None:
        return []
    if int(node["id"]) in SYSTEM_STORAGE_NODE_IDS or str(node["node_type"] or "") == "system":
        return []
    rows, cols = default_grid_for_node(node["rows"], node["cols"])
    if rows == 1 and cols == 1:
        return []
    return [grid_label(index, cols) for index in range(1, rows * cols + 1)]


def sequential_frame_positions(
    conn: sqlite3.Connection,
    node_id: int | None,
    count: int,
    start_position: str | None = None,
) -> list[str | None]:
    if count <= 0:
        return []
    node = get_node(conn, node_id)
    coords = position_options_for_node(node)
    if not coords:
        return [None] * count
    start = (start_position or "").strip()
    start_index = coords.index(start) if start in coords else 0
    occupied = set(occupied_positions(conn, int(node_id))) | occupied_child_positions(conn, int(node_id))
    available = [coord for coord in coords[start_index:] if coord not in occupied]
    positions: list[str | None] = []
    for index in range(count):
        position = available[index] if index < len(available) else None
        if position:
            occupied.add(position)
        positions.append(position)
    return positions


def get_node(conn: sqlite3.Connection, node_id: int | None) -> sqlite3.Row | None:
    if node_id is None:
        return None
    return conn.execute("SELECT * FROM storage_nodes WHERE id = ?", (node_id,)).fetchone()


def node_path(conn: sqlite3.Connection, node_id: int | None) -> list[dict[str, Any]]:
    path: list[dict[str, Any]] = []
    if is_system_storage_node_id(node_id):
        return [{"id": int(node_id), "name": system_storage_label(node_id), "node_type": "system"}]
    current = get_node(conn, node_id)
    guard = 0
    while current is not None and guard < 100:
        path.append(row_dict(current) or {})
        current = get_node(conn, current["parent_id"])
        guard += 1
    path.reverse()
    return path


def node_full_path(conn: sqlite3.Connection, node_id: int | None) -> str:
    if is_system_storage_node_id(node_id):
        return system_storage_label(node_id)
    return " / ".join(node["name"] for node in node_path(conn, node_id))


def storage_location_text(conn: sqlite3.Connection, node_id: int, position: str | None = None) -> str:
    if not node_id:
        return ""
    if is_system_storage_node_id(node_id):
        return system_storage_label(node_id)
    clean_position = (position or "").strip()
    full_path = node_full_path(conn, node_id)
    return f"{full_path}；{clean_position}" if clean_position else full_path


def storage_location_from_path(path_cache: dict[int, str], node_id: int, position: str | None = None) -> str:
    if not node_id:
        return ""
    if is_system_storage_node_id(node_id):
        return system_storage_label(node_id)
    clean_position = (position or "").strip()
    full_path = path_cache.get(int(node_id), "")
    return f"{full_path}；{clean_position}" if clean_position else full_path


def descendant_node_ids(conn: sqlite3.Connection, node_id: int, include_self: bool = True) -> list[int]:
    if is_system_storage_node_id(node_id):
        return [int(node_id)] if include_self else []
    ids = [node_id] if include_self else []
    children = conn.execute("SELECT id FROM storage_nodes WHERE parent_id = ?", (node_id,)).fetchall()
    for child in children:
        ids.extend(descendant_node_ids(conn, int(child["id"]), include_self=True))
    return ids


def batch_node_paths_and_descendants(conn: sqlite3.Connection) -> tuple[dict[int, str], dict[int, list[int]]]:
    """一次查询所有节点的路径文本和后代 ID，避免 N+1 循环。"""
    rows = conn.execute("SELECT id, parent_id, name FROM storage_nodes ORDER BY id").fetchall()
    parent_map: dict[int, int | None] = {}
    name_map: dict[int, str] = {}
    children_map: dict[int | None, list[int]] = {}
    for row in rows:
        nid = int(row["id"])
        pid = row["parent_id"]
        parent_map[nid] = int(pid) if pid else None
        name_map[nid] = row["name"]
        children_map.setdefault(pid, []).append(nid)

    path_cache: dict[int, str] = {}
    for nid in name_map:
        parts: list[str] = []
        cursor: int | None = nid
        guard = 0
        while cursor is not None and guard < 100:
            if cursor in path_cache:
                parts = path_cache[cursor].split(" / ") + parts
                break
            parts.insert(0, name_map.get(cursor, ""))
            cursor = parent_map.get(cursor)
            guard += 1
        path_cache[nid] = " / ".join(parts)

    descendant_cache: dict[int, list[int]] = {}

    def _collect(nid: int) -> list[int]:
        if nid in descendant_cache:
            return descendant_cache[nid]
        result = [nid]
        for child_id in children_map.get(nid, []):
            result.extend(_collect(child_id))
        descendant_cache[nid] = result
        return result

    for nid in name_map:
        _collect(nid)

    return path_cache, descendant_cache


def computed_storage_location(
    conn: sqlite3.Connection,
    item: dict[str, Any],
    path_cache: dict[int, str] | None = None,
) -> str:
    node_id = item.get("storage_node_id")
    if not node_id:
        return system_storage_label(default_storage_node_for_status(item.get("status")))
    if path_cache is not None:
        return storage_location_from_path(path_cache, int(node_id), str(item.get("grid_cell") or "").strip() or None)
    return storage_location_text(conn, int(node_id), str(item.get("grid_cell") or "").strip() or None)


def normalize_reagent_item(
    row: sqlite3.Row,
    conn: sqlite3.Connection | None = None,
    path_cache: dict[int, str] | None = None,
) -> dict[str, Any]:
    item = row_dict(row) or {}
    source_code = item.get("source_code") or item.get("code") or item.get("id")
    if conn is not None:
        item["storage_location"] = computed_storage_location(conn, item, path_cache)
    item.update(
        {
            "item_type": "reagent",
            "code": item.get("code") or item.get("id"),
            "display_name": item.get("name") or "",
            "display_type": item.get("category") or "试剂",
            "source_code": source_code,
            "validation_status": VALIDATION_UNVERIFIED,
        }
    )
    return item


def normalize_sample_item(
    row: sqlite3.Row,
    conn: sqlite3.Connection | None = None,
    path_cache: dict[int, str] | None = None,
) -> dict[str, Any]:
    item = row_dict(row) or {}
    name = item.get("name") or "临床标本"
    code = item.get("code") or item.get("id")
    if conn is not None:
        item["storage_location"] = computed_storage_location(conn, item, path_cache)
    item.update(
        {
            "item_type": "sample",
            "code": code,
            "name": name,
            "display_name": name,
            "category": item.get("category") or "临床标本",
            "display_type": item.get("category") or "临床标本",
        }
    )
    return item


def attach_aliquot_totals(conn: sqlite3.Connection, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sample_sources = sorted({
        str(item.get("source_code") or item.get("code") or "").strip()
        for item in items
        if item.get("item_type") == "sample" and str(item.get("source_code") or item.get("code") or "").strip()
    })
    reagent_sources = sorted({
        str(item.get("source_code") or item.get("code") or "").strip()
        for item in items
        if item.get("item_type") == "reagent" and str(item.get("source_code") or item.get("code") or "").strip()
    })
    sample_totals: dict[str, int] = {}
    reagent_totals: dict[str, int] = {}
    if sample_sources:
        placeholders = ",".join("?" for _ in sample_sources)
        rows = conn.execute(
            f"SELECT COALESCE(source_code, code, id) AS source, COUNT(*) AS n FROM clinical_samples WHERE COALESCE(source_code, code, id) IN ({placeholders}) GROUP BY COALESCE(source_code, code, id)",
            sample_sources,
        ).fetchall()
        sample_totals = {str(row["source"]): int(row["n"]) for row in rows}
    if reagent_sources:
        placeholders = ",".join("?" for _ in reagent_sources)
        rows = conn.execute(
            f"""
            SELECT COALESCE(source_code, code, id) AS source, COUNT(*) AS n
            FROM reagents
            WHERE COALESCE(source_code, code, id) IN ({placeholders})
            GROUP BY COALESCE(source_code, code, id)
            """,
            reagent_sources,
        ).fetchall()
        reagent_totals = {str(row["source"]): int(row["n"]) for row in rows}
    for item in items:
        source = str(item.get("source_code") or item.get("code") or "").strip()
        if item.get("item_type") == "sample":
            item["aliquot_total"] = sample_totals.get(source, 1)
        elif item.get("item_type") == "reagent":
            item["aliquot_total"] = reagent_totals.get(source, 1)
    return items


def storage_item_counts(conn: sqlite3.Connection, visible_types: set[str] | None = None) -> dict[int, int]:
    visible = _visible_inventory_types(visible_types)
    subqueries = []
    if "reagent" in visible:
        subqueries.append(f"""
            SELECT storage_node_id FROM reagents
            WHERE storage_node_id > 0 AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
        """)
    if "sample" in visible:
        subqueries.append(f"""
            SELECT storage_node_id FROM clinical_samples
            WHERE storage_node_id > 0 AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}
        """)
    if not subqueries:
        return {}
    rows = conn.execute(
        f"""
        SELECT storage_node_id, COUNT(*) AS n
        FROM (
            {" UNION ALL ".join(subqueries)}
        )
        GROUP BY storage_node_id
        """
    ).fetchall()
    return {int(row["storage_node_id"]): int(row["n"]) for row in rows}


def unplaced_item_count(conn: sqlite3.Connection, visible_types: set[str] | None = None) -> int:
    visible = _visible_inventory_types(visible_types)
    count = 0
    if "reagent" in visible:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM reagents
            WHERE storage_node_id = {SYSTEM_UNPLACED_NODE_ID}
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            """
        ).fetchone()
        count += int(row["n"] or 0)
    if "sample" in visible:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM clinical_samples
            WHERE storage_node_id = {SYSTEM_UNPLACED_NODE_ID}
              AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}
            """
        ).fetchone()
        count += int(row["n"] or 0)
    return count


def find_position_owner(
    conn: sqlite3.Connection,
    node_id: int,
    position: str | None,
    exclude_type: str = "",
    exclude_id: int | None = None,
) -> dict[str, Any] | None:
    clean_position = (position or "").strip()
    if not clean_position:
        return None
    reagent = conn.execute(
        f"""
        SELECT id, code, name FROM reagents
        WHERE storage_node_id = ? AND grid_cell = ?
          AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
          AND NOT (? = 'reagent' AND id = ?)
        LIMIT 1
        """,
        (node_id, clean_position, exclude_type, exclude_id or 0),
    ).fetchone()
    if reagent:
        return {"item_type": "reagent", "code": reagent["code"] or reagent["id"], "name": reagent["name"]}
    sample = conn.execute(
        f"""
        SELECT id, code, aliquot_no, name FROM clinical_samples
        WHERE storage_node_id = ? AND grid_cell = ?
          AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}
          AND NOT (? = 'sample' AND id = ?)
        LIMIT 1
        """,
        (node_id, clean_position, exclude_type, exclude_id or 0),
    ).fetchone()
    if sample:
        source = sample["code"] or sample["id"]
        return {"item_type": "sample", "code": source, "name": sample["name"]}
    return None


def occupied_child_positions(conn: sqlite3.Connection, node_id: int) -> set[str]:
    node = get_node(conn, node_id)
    if node is None:
        return set()
    _, cols = default_grid_for_node(node["rows"], node["cols"])
    children = [
        row_dict(row) or {}
        for row in conn.execute(
            """
            SELECT * FROM storage_nodes
            WHERE parent_id = ? AND grid_row IS NOT NULL AND grid_col IS NOT NULL
            ORDER BY sort_order, id
            """,
            (node_id,),
        ).fetchall()
    ]
    assign_grid_positions(children, cols)
    return {str(child.get("grid_label") or "") for child in children if child.get("grid_label")}


def find_child_position_owner(conn: sqlite3.Connection, node_id: int, position: str | None) -> dict[str, Any] | None:
    clean_position = (position or "").strip()
    if not clean_position:
        return None
    node = get_node(conn, node_id)
    if node is None:
        return None
    _, cols = default_grid_for_node(node["rows"], node["cols"])
    children = [
        row_dict(row) or {}
        for row in conn.execute(
            """
            SELECT * FROM storage_nodes
            WHERE parent_id = ? AND grid_row IS NOT NULL AND grid_col IS NOT NULL
            ORDER BY sort_order, id
            """,
            (node_id,),
        ).fetchall()
    ]
    assign_grid_positions(children, cols)
    for child in children:
        if str(child.get("grid_label") or "") == clean_position:
            return {"item_type": "storage-node", "code": child.get("id"), "name": child.get("name") or "下级空间"}
    return None


def inventory_items_at_node(
    conn: sqlite3.Connection,
    node_id: int,
    direct_only: bool = False,
    limit: int = 500,
    visible_types: set[str] | None = None,
) -> list[dict[str, Any]]:
    node_ids = [node_id] if direct_only else descendant_node_ids(conn, node_id, True)
    if not node_ids:
        return []
    placeholders = ",".join("?" for _ in node_ids)
    visible = _visible_inventory_types(visible_types)
    reagents = []
    samples = []
    if "reagent" in visible:
        reagents = [
            normalize_reagent_item(row, conn)
            for row in conn.execute(
                f"SELECT * FROM reagents WHERE storage_node_id IN ({placeholders}) AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}",
                node_ids,
            ).fetchall()
        ]
    if "sample" in visible:
        samples = [
            normalize_sample_item(row, conn)
            for row in conn.execute(
                f"SELECT * FROM clinical_samples WHERE storage_node_id IN ({placeholders}) AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}",
                node_ids,
            ).fetchall()
        ]
    items = reagents + samples
    attach_reagent_validation_statuses(conn, reagents)
    attach_aliquot_totals(conn, items)
    items.sort(key=lambda item: (str(item.get("grid_cell") or ""), str(item.get("updated_at") or ""), str(item.get("code") or "")), reverse=True)
    return items[:limit]


def unplaced_inventory_items(conn: sqlite3.Connection, limit: int = 500, visible_types: set[str] | None = None) -> list[dict[str, Any]]:
    visible = _visible_inventory_types(visible_types)
    reagents = []
    samples = []
    if "reagent" in visible:
        reagents = [
            normalize_reagent_item(row, conn)
            for row in conn.execute(
                f"""
                SELECT * FROM reagents
                WHERE storage_node_id = {SYSTEM_UNPLACED_NODE_ID}
                  AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
    if "sample" in visible:
        samples = [
            normalize_sample_item(row, conn)
            for row in conn.execute(
                f"""
                SELECT * FROM clinical_samples
                WHERE storage_node_id = {SYSTEM_UNPLACED_NODE_ID}
                  AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        ]
    items = reagents + samples
    attach_reagent_validation_statuses(conn, reagents)
    attach_aliquot_totals(conn, items)
    items.sort(key=lambda item: (str(item.get("updated_at") or ""), int(item.get("id") or 0)), reverse=True)
    return items[:limit]


def occupied_positions(conn: sqlite3.Connection, node_id: int) -> dict[str, dict[str, Any]]:
    items = inventory_items_at_node(conn, node_id, direct_only=True)
    return {str(item["grid_cell"]): item for item in items if item.get("grid_cell")}


def inventory_item_by_id(conn: sqlite3.Connection, item_type: str, item_id: int) -> dict[str, Any] | None:
    if item_type == "sample":
        row = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (item_id,)).fetchone()
        items = [normalize_sample_item(row, conn)] if row else []
        attach_aliquot_totals(conn, items)
        return items[0] if items else None
    row = conn.execute("SELECT * FROM reagents WHERE id = ?", (item_id,)).fetchone()
    items = [normalize_reagent_item(row, conn)] if row else []
    attach_reagent_validation_statuses(conn, items)
    attach_aliquot_totals(conn, items)
    return items[0] if items else None


def validate_storage_parent(conn: sqlite3.Connection, parent_id: int | None) -> None:
    if parent_id is None:
        return
    parent = get_node(conn, parent_id)
    if parent is None:
        raise ApiError(400, "父级空间不存在")


def assign_inventory_item_to_node(
    conn: sqlite3.Connection,
    item_type: str,
    item_id: int,
    node_id: int | None,
    user_id: int | None,
    position: str | None = None,
) -> None:
    table = INVENTORY_TABLES[item_type]
    if node_id is None:
        node_id = SYSTEM_UNPLACED_NODE_ID
    node_id = int(node_id)
    if is_system_storage_node_id(node_id):
        conn.execute(
            f"""
            UPDATE {table}
            SET storage_node_id = ?, grid_cell = NULL,
                updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (node_id, user_id, now_text(), item_id),
        )
        return
    node = get_node(conn, node_id)
    if node is None:
        raise ApiError(400, "存放空间不存在")
    clean_position = (position or "").strip() or None
    allowed_positions = position_options_for_node(node)
    if clean_position and clean_position not in allowed_positions:
        raise ApiError(400, "当前空间不支持该格位")
    if clean_position:
        child = find_child_position_owner(conn, node_id, clean_position)
        if child:
            raise ApiError(409, "已占用")
        existing = find_position_owner(conn, node_id, clean_position, item_type, item_id)
        if existing:
            raise ApiError(409, "已占用")
    conn.execute(
        f"""
        UPDATE {table}
        SET storage_node_id = ?, grid_cell = ?,
            updated_by = ?, updated_at = ?
        WHERE id = ?
        """,
        (node_id, clean_position, user_id, now_text(), item_id),
    )


def assign_reagent_to_node(conn: sqlite3.Connection, reagent_id: int, node_id: int | None, user_id: int | None, position: str | None = None) -> None:
    assign_inventory_item_to_node(conn, "reagent", reagent_id, node_id, user_id, position)


def assign_sample_to_node(conn: sqlite3.Connection, sample_id: int, node_id: int | None, user_id: int | None, position: str | None = None) -> None:
    assign_inventory_item_to_node(conn, "sample", sample_id, node_id, user_id, position)


def refresh_inventory_locations_at_node(conn: sqlite3.Connection, node_id: int) -> None:
    timestamp = now_text()
    for table in INVENTORY_TABLES.values():
        conn.execute(f"UPDATE {table} SET updated_at = ? WHERE storage_node_id = ?", (timestamp, node_id))


def reagent_is_consumed(status: str | None, quantity: Any) -> bool:
    if status == STATUS_CONSUMED:
        return True
    if status == STATUS_ORDERED:
        return False
    try:
        return quantity is not None and safe_float(quantity, 0) <= 0
    except (TypeError, ValueError):
        return False


def reagent_should_leave_storage(status: str | None, quantity: Any) -> bool:
    """已订购没有实物位置；已耗尽或数量归零会释放位置。"""
    return not occupies_storage(status) or reagent_is_consumed(status, quantity)


def normalize_consumed_reagent_fields(values: dict[str, Any]) -> None:
    if reagent_is_consumed(str(values.get("status", "")).strip() or None, values.get("quantity")):
        values["status"] = STATUS_CONSUMED
        values["quantity"] = 0


def release_reagent_storage(conn: sqlite3.Connection, reagent_id: int, user_id: int | None) -> None:
    reagent = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
    if reagent is None:
        raise ApiError(404, "试剂不存在")
    from_node_id = reagent["storage_node_id"]
    from_position = str(reagent["grid_cell"] or "").strip() or None
    from_location = storage_location_text(conn, int(from_node_id), from_position) if from_node_id else ""
    had_position = bool(from_node_id or from_position or from_location)
    if not had_position:
        return
    timestamp = now_text()
    status = str(reagent["status"] or "").strip() or STATUS_DISABLED
    consumed = status == STATUS_CONSUMED
    target_node_id = SYSTEM_CHECKED_OUT_NODE_ID if consumed else SYSTEM_NOT_ARRIVED_NODE_ID
    if int(from_node_id or 0) == target_node_id and not from_position:
        return
    target_location = storage_location_text(conn, target_node_id)
    reason = MOVEMENT_REASON_STATUS
    note = "实物已从原位置取出，试剂和验证记录保留。" if consumed else "状态为已订购，未形成可占用位置的实物库存。"
    assign_reagent_to_node(conn, reagent_id, target_node_id, user_id)
    if from_location:
        conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
                 to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
                 moved_by, moved_at, reason, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                "试剂", reagent["code"] or str(reagent_id), "reagent", reagent_id,
                from_node_id, from_position, target_node_id, from_location, target_location, user_id, timestamp,
                reason, note,
            ),
        )


def release_sample_storage(conn: sqlite3.Connection, sample_id: int, user_id: int | None) -> None:
    sample = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
    if sample is None:
        raise ApiError(404, "临床标本不存在")
    from_node_id = sample["storage_node_id"]
    from_position = str(sample["grid_cell"] or "").strip() or None
    if int(from_node_id or 0) == SYSTEM_CHECKED_OUT_NODE_ID and not from_position:
        return
    from_location = storage_location_text(conn, int(from_node_id), from_position) if from_node_id else ""
    assign_sample_to_node(conn, sample_id, SYSTEM_CHECKED_OUT_NODE_ID, user_id)
    if from_location:
        timestamp = now_text()
        conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
                 to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
                 moved_by, moved_at, reason, note)
            VALUES (?, ?, 'sample', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                "临床标本", sample["code"] or str(sample_id), sample_id,
                from_node_id, from_position, SYSTEM_CHECKED_OUT_NODE_ID,
                from_location, storage_location_text(conn, SYSTEM_CHECKED_OUT_NODE_ID),
                user_id, timestamp, MOVEMENT_REASON_STATUS, "状态调整为已耗尽，标本不再占用实物位置。",
            ),
        )
