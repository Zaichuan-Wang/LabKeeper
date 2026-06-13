from __future__ import annotations

import sqlite3
from typing import Any

from core.common import ApiError, now_text, row_dict, safe_float

INVENTORY_TABLES = {
    "reagent": "reagents",
    "sample": "clinical_samples",
}

PHYSICAL_INVENTORY_STATUSES = ("可用", "停用")


def occupies_storage(status: str | None) -> bool:
    return str(status or "").strip() in PHYSICAL_INVENTORY_STATUSES


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


def default_grid_for_node(node_type: str, rows: int | None, cols: int | None) -> tuple[int, int]:
    if rows and cols:
        return int(rows), int(cols)
    if node_type == "box":
        return int(rows or 9), int(cols or 9)
    return int(rows or 1), int(cols or 1)


def clean_positive_int(value: Any, maximum: int = 50) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return min(number, maximum)


def clean_node_dimension(node_type: str, field: str, value: Any) -> int | None:
    maximum = 26 if node_type == "box" and field == "rows" else 50
    return clean_positive_int(value, maximum)


def coord_list(rows: int, cols: int) -> list[str]:
    coords = []
    for row in range(rows):
        label = chr(ord("A") + row)
        for col in range(1, cols + 1):
            coords.append(f"{label}{col}")
    return coords


def position_options_for_node(node: sqlite3.Row | dict[str, Any] | None) -> list[str]:
    if node is None:
        return []
    rows, cols = default_grid_for_node(str(node["node_type"]), node["rows"], node["cols"])
    if str(node["node_type"]) == "box":
        return coord_list(rows, cols)
    if rows == 1 and cols == 1:
        return []
    return [grid_label(index, cols) for index in range(1, rows * cols + 1)]


def sequential_box_positions(
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
    current = get_node(conn, node_id)
    guard = 0
    while current is not None and guard < 100:
        path.append(row_dict(current) or {})
        current = get_node(conn, current["parent_id"])
        guard += 1
    path.reverse()
    return path


def node_full_path(conn: sqlite3.Connection, node_id: int | None) -> str:
    return " / ".join(node["name"] for node in node_path(conn, node_id))


def storage_location_text(conn: sqlite3.Connection, node_id: int, position: str | None = None) -> str:
    if not node_id:
        return ""
    clean_position = (position or "").strip()
    full_path = node_full_path(conn, node_id)
    return f"{full_path}；{clean_position}" if clean_position else full_path


def storage_location_from_path(path_cache: dict[int, str], node_id: int, position: str | None = None) -> str:
    if not node_id:
        return ""
    clean_position = (position or "").strip()
    full_path = path_cache.get(int(node_id), "")
    return f"{full_path}；{clean_position}" if clean_position else full_path


def descendant_node_ids(conn: sqlite3.Connection, node_id: int, include_self: bool = True) -> list[int]:
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
        return "未归位" if occupies_storage(item.get("status")) else ""
    if path_cache is not None:
        return storage_location_from_path(path_cache, int(node_id), str(item.get("position_in_box") or "").strip() or None)
    return storage_location_text(conn, int(node_id), str(item.get("position_in_box") or "").strip() or None)


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
            "validation_status": item.get("validation_status") or "",
            "expiration_date": item.get("expiration_date") or "",
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


def storage_item_counts(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(
        """
        SELECT storage_node_id, COUNT(*) AS n
        FROM (
            SELECT storage_node_id FROM reagents
            WHERE storage_node_id IS NOT NULL AND COALESCE(status, '') IN ('可用', '停用')
            UNION ALL
            SELECT storage_node_id FROM clinical_samples
            WHERE storage_node_id IS NOT NULL AND status IN ('可用', '停用')
        )
        GROUP BY storage_node_id
        """
    ).fetchall()
    return {int(row["storage_node_id"]): int(row["n"]) for row in rows}


def unplaced_item_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT SUM(n) AS n
        FROM (
            SELECT COUNT(*) AS n
            FROM reagents
            WHERE storage_node_id IS NULL
              AND COALESCE(status, '') IN ('可用', '停用')
            UNION ALL
            SELECT COUNT(*) AS n
            FROM clinical_samples
            WHERE storage_node_id IS NULL
              AND status IN ('可用', '停用')
        )
        """
    ).fetchone()
    return int(row["n"] or 0)


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
        """
        SELECT id, code, name FROM reagents
        WHERE storage_node_id = ? AND position_in_box = ?
          AND COALESCE(status, '') IN ('可用', '停用')
          AND NOT (? = 'reagent' AND id = ?)
        LIMIT 1
        """,
        (node_id, clean_position, exclude_type, exclude_id or 0),
    ).fetchone()
    if reagent:
        return {"item_type": "reagent", "code": reagent["code"] or reagent["id"], "name": reagent["name"]}
    sample = conn.execute(
        """
        SELECT id, code, aliquot_no, name FROM clinical_samples
        WHERE storage_node_id = ? AND position_in_box = ?
          AND status IN ('可用', '停用')
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
    _, cols = default_grid_for_node(str(node["node_type"]), node["rows"], node["cols"])
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
    _, cols = default_grid_for_node(str(node["node_type"]), node["rows"], node["cols"])
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


def inventory_items_at_node(conn: sqlite3.Connection, node_id: int, direct_only: bool = False, limit: int = 500) -> list[dict[str, Any]]:
    node_ids = [node_id] if direct_only else descendant_node_ids(conn, node_id, True)
    if not node_ids:
        return []
    placeholders = ",".join("?" for _ in node_ids)
    reagents = [
        normalize_reagent_item(row, conn)
        for row in conn.execute(
            f"SELECT * FROM reagents WHERE storage_node_id IN ({placeholders}) AND COALESCE(status, '') IN ('可用', '停用')",
            node_ids,
        ).fetchall()
    ]
    samples = [
        normalize_sample_item(row, conn)
        for row in conn.execute(
            f"SELECT * FROM clinical_samples WHERE storage_node_id IN ({placeholders}) AND status IN ('可用', '停用')",
            node_ids,
        ).fetchall()
    ]
    items = reagents + samples
    attach_aliquot_totals(conn, items)
    items.sort(key=lambda item: (str(item.get("position_in_box") or ""), str(item.get("updated_at") or ""), str(item.get("code") or "")), reverse=True)
    return items[:limit]


def unplaced_inventory_items(conn: sqlite3.Connection, limit: int = 500) -> list[dict[str, Any]]:
    reagents = [
        normalize_reagent_item(row, conn)
        for row in conn.execute(
            """
            SELECT * FROM reagents
            WHERE storage_node_id IS NULL
              AND COALESCE(status, '') IN ('可用', '停用')
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    ]
    samples = [
        normalize_sample_item(row, conn)
        for row in conn.execute(
            """
            SELECT * FROM clinical_samples
            WHERE storage_node_id IS NULL
              AND status IN ('可用', '停用')
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    ]
    items = reagents + samples
    attach_aliquot_totals(conn, items)
    items.sort(key=lambda item: (str(item.get("updated_at") or ""), int(item.get("id") or 0)), reverse=True)
    return items[:limit]


def occupied_positions(conn: sqlite3.Connection, node_id: int) -> dict[str, dict[str, Any]]:
    items = inventory_items_at_node(conn, node_id, direct_only=True)
    return {str(item["position_in_box"]): item for item in items if item.get("position_in_box")}


def inventory_item_by_id(conn: sqlite3.Connection, item_type: str, item_id: int) -> dict[str, Any] | None:
    if item_type == "sample":
        row = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (item_id,)).fetchone()
        items = [normalize_sample_item(row, conn)] if row else []
        attach_aliquot_totals(conn, items)
        return items[0] if items else None
    row = conn.execute("SELECT * FROM reagents WHERE id = ?", (item_id,)).fetchone()
    items = [normalize_reagent_item(row, conn)] if row else []
    attach_aliquot_totals(conn, items)
    return items[0] if items else None


def validate_storage_parent(conn: sqlite3.Connection, node_type: str, parent_id: int | None) -> None:
    if parent_id is None:
        return
    parent = get_node(conn, parent_id)
    if parent is None:
        raise ApiError(400, "父级空间不存在")
    if parent["node_type"] == "box":
        raise ApiError(400, "盒子已是末端空间，不能在盒子下继续新建空间")


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
        conn.execute(
            f"""
            UPDATE {table}
            SET storage_node_id = NULL, position_in_box = NULL,
                updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (user_id, now_text(), item_id),
        )
        return
    node = get_node(conn, node_id)
    if node is None:
        raise ApiError(400, "空间类型不正确")
    clean_position = (position or "").strip() or None
    allowed_positions = position_options_for_node(node)
    if clean_position and clean_position not in allowed_positions:
        raise ApiError(400, "当前空间不支持该格位")
    if clean_position:
        child = find_child_position_owner(conn, node_id, clean_position)
        if child:
            raise ApiError(409, f"格位 {clean_position} 已被 {child['name']} 占用")
        existing = find_position_owner(conn, node_id, clean_position, item_type, item_id)
        if existing:
            raise ApiError(409, f"格位 {clean_position} 已被 {existing['code']} · {existing['name']} 占用")
    conn.execute(
        f"""
        UPDATE {table}
        SET storage_node_id = ?, position_in_box = ?,
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
    if status == "已耗尽":
        return True
    if status == "已订购":
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
        values["status"] = "已耗尽"
        values["quantity"] = 0


def release_reagent_storage(conn: sqlite3.Connection, reagent_id: int, user_id: int | None) -> None:
    reagent = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
    if reagent is None:
        raise ApiError(404, "试剂不存在")
    from_node_id = reagent["storage_node_id"]
    from_position = str(reagent["position_in_box"] or "").strip() or None
    from_location = storage_location_text(conn, int(from_node_id), from_position) if from_node_id else ""
    had_position = bool(from_node_id or from_position or from_location)
    if not had_position:
        return
    timestamp = now_text()
    status = str(reagent["status"] or "").strip() or "停用"
    target_location = "未放置（已耗尽）" if status == "已耗尽" else "未放置（未到货）"
    reason = "试剂耗尽" if status == "已耗尽" else "订购状态调整"
    note = "实物已从原位置取出，试剂和验证记录保留。" if status == "已耗尽" else "状态为已订购，未形成可占用位置的实物库存。"
    assign_reagent_to_node(conn, reagent_id, None, user_id)
    if from_location:
        conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_position_in_box,
                 to_storage_node_id, to_position_in_box, from_location_snapshot, to_location_snapshot,
                 moved_by, moved_at, reason, note)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                "试剂", reagent["code"] or str(reagent_id), "reagent", reagent_id,
                from_node_id, from_position, from_location, target_location, user_id, timestamp,
                reason, note,
            ),
        )


def release_sample_storage(conn: sqlite3.Connection, sample_id: int, user_id: int | None) -> None:
    sample = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
    if sample is None:
        raise ApiError(404, "临床标本不存在")
    assign_sample_to_node(conn, sample_id, None, user_id)
