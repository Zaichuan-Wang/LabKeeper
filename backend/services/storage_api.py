from __future__ import annotations

from typing import Any

from core.common import ApiError, clean_int_range, clean_optional_positive_int, create_audit, now_text, row_dict, rows_list
from core.constants import MOVEMENT_REASON_SPACE_MOVE, SYSTEM_UNPLACED_NODE_ID
from db.database import connect
from services.storage_inventory import (
    assign_grid_positions,
    batch_node_paths_and_descendants,
    clean_positive_int,
    default_grid_for_node,
    descendant_node_ids,
    get_node,
    grid_label,
    find_position_owner,
    inventory_item_by_id,
    inventory_items_at_node,
    node_full_path,
    position_options_for_node,
    refresh_inventory_locations_at_node,
    storage_item_counts,
    storage_location_text,
    unplaced_inventory_items,
    unplaced_item_count,
    validate_storage_parent,
)
from services.options_config import clean_space_type_code


VIRTUAL_UNPLACED_NODE_ID = SYSTEM_UNPLACED_NODE_ID
VIRTUAL_FAVORITES_NODE_ID = -5
DEFAULT_ROOT_STORAGE_NODE_ID = 1


def is_virtual_unplaced_id(node_id: Any) -> bool:
    try:
        return int(node_id) == VIRTUAL_UNPLACED_NODE_ID
    except (TypeError, ValueError):
        return False


def is_virtual_favorites_id(node_id: Any) -> bool:
    try:
        return int(node_id) == VIRTUAL_FAVORITES_NODE_ID
    except (TypeError, ValueError):
        return False


def _grid_label_for_parent(conn: Any, parent_id: int | None, grid_row: Any, grid_col: Any) -> str | None:
    if not parent_id or not (grid_row and grid_col):
        return None
    parent = get_node(conn, parent_id)
    if parent is None:
        return None
    _, cols = default_grid_for_node(parent["rows"], parent["cols"])
    return grid_label((int(grid_row) - 1) * int(cols or 1) + int(grid_col), int(cols or 1))


def storage_node_position_snapshot(conn: Any, parent_id: int | None, grid_row: Any, grid_col: Any) -> str:
    if not parent_id:
        return "未归位"
    if get_node(conn, parent_id) is None:
        return ""
    return storage_location_text(conn, int(parent_id), _grid_label_for_parent(conn, parent_id, grid_row, grid_col))


def storage_node_grid_label(conn: Any, parent_id: int | None, grid_row: Any, grid_col: Any) -> str | None:
    return _grid_label_for_parent(conn, parent_id, grid_row, grid_col)


def validate_storage_grid_target(conn: Any, node_id: int, parent_id: int | None, grid_row: Any, grid_col: Any) -> None:
    if not parent_id or not (grid_row and grid_col):
        return
    label = _grid_label_for_parent(conn, parent_id, grid_row, grid_col)
    if label is None:
        return
    sibling = conn.execute(
        """
        SELECT id, name FROM storage_nodes
        WHERE parent_id = ? AND grid_row = ? AND grid_col = ? AND id <> ?
        LIMIT 1
        """,
        (parent_id, grid_row, grid_col, node_id),
    ).fetchone()
    if sibling:
        raise ApiError(409, "已占用")
    existing = find_position_owner(conn, parent_id, label)
    if existing:
        raise ApiError(409, "已占用")


def storage_tree(visible_types: set[str] | None = None) -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT n.*, p.name AS parent_name
            FROM storage_nodes n LEFT JOIN storage_nodes p ON p.id = n.parent_id
            WHERE n.id > 0 AND COALESCE(n.node_type, 'space') != 'system'
            ORDER BY COALESCE(n.parent_id, 0), n.sort_order, n.name
            """
        ).fetchall()
        counts = storage_item_counts(conn, visible_types)
        path_cache, desc_cache = batch_node_paths_and_descendants(conn)
        items = []
        for row in rows:
            item = row_dict(row) or {}
            nid = int(item["id"])
            item["path"] = path_cache.get(nid, "")
            item["direct_items"] = counts.get(nid, 0)
            item["total_items"] = sum(counts.get(i, 0) for i in desc_cache.get(nid, [nid]))
            items.append(item)
    return {"items": items, "count": len(items)}


def storage_child_items(conn: Any, rows: list[Any], direct_counts: dict[int, int], node_id: int, path_cache: dict[int, str] | None = None, desc_cache: dict[int, list[int]] | None = None) -> list[dict[str, Any]]:
    child_items = []
    for row in rows:
        if int(row["id"]) <= 0 or str(row["node_type"] or "") == "system":
            continue
        if int(row["parent_id"] or 0) != int(node_id):
            continue
        item = row_dict(row) or {}
        nid = int(item["id"])
        item["path"] = path_cache.get(nid, "") if path_cache else node_full_path(conn, nid)
        item["children"] = len(conn.execute("SELECT id FROM storage_nodes WHERE parent_id = ?", (item["id"],)).fetchall())
        ids = desc_cache.get(nid, [nid]) if desc_cache else descendant_node_ids(conn, nid, True)
        item["direct"] = direct_counts.get(nid, 0)
        item["total"] = sum(direct_counts.get(i, 0) for i in ids)
        item["direct_items"] = item["direct"]
        item["total_items"] = item["total"]
        item["is_unplaced"] = not bool(item.get("grid_row") and item.get("grid_col"))
        item["grid_position"] = None
        item["grid_label"] = ""
        child_items.append(item)
    return child_items


def _validation_rows_for_item(conn: Any, item: dict[str, Any] | None) -> list[Any]:
    if not item or item.get("item_type") != "reagent":
        return []
    catalog_no = str(item.get("catalog_no") or "").strip()
    if not catalog_no:
        return []
    return conn.execute(
        """
        SELECT
            v.id, NULL AS item_id, v.catalog_no,
            v.validator_id, v.validation_date, v.method, v.result, v.description, v.image_path, v.created_at,
            u.display_name AS validator_name
        FROM validations v
        LEFT JOIN users u ON u.id = v.validator_id
        WHERE v.catalog_no = ?
        ORDER BY v.validation_date DESC, v.created_at DESC
        """,
        (catalog_no,),
    ).fetchall()


def storage_visual(
    node_id: int | None = None,
    selected_well: str = "",
    selected_item_type: str = "",
    selected_item_id: int | None = None,
    visible_types: set[str] | None = None,
) -> dict[str, Any]:
    visible = {"reagent", "sample"} if visible_types is None else visible_types
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM storage_nodes
            WHERE id > 0 AND COALESCE(node_type, 'space') != 'system'
            ORDER BY COALESCE(parent_id, 0), sort_order, name
            """
        ).fetchall()
        direct_counts = storage_item_counts(conn, visible_types)
        path_cache, desc_cache = batch_node_paths_and_descendants(conn)
        parent_by_id = {int(row["id"]): row["parent_id"] for row in rows}

        def depth_for(nid: int) -> int:
            depth = 0
            parent = parent_by_id.get(nid)
            guard = 0
            while parent and guard < 100:
                depth += 1
                parent = parent_by_id.get(int(parent))
                guard += 1
            return depth

        selected_unplaced = is_virtual_unplaced_id(node_id)
        selected_favorites = is_virtual_favorites_id(node_id)
        virtual_count = unplaced_item_count(conn, visible_types)
        tree = [{
            "id": VIRTUAL_UNPLACED_NODE_ID,
            "parent_id": None,
            "name": "未归位",
            "path": "未归位",
            "depth": 0,
            "selected": selected_unplaced,
            "direct_items": virtual_count,
            "total_items": virtual_count,
            "is_virtual_unplaced": True,
        }, {
            "id": VIRTUAL_FAVORITES_NODE_ID,
            "parent_id": None,
            "name": "常用位置",
            "path": "常用位置",
            "depth": 0,
            "selected": selected_favorites,
            "direct_items": 0,
            "total_items": 0,
            "is_virtual_favorites": True,
        }]
        for row in rows:
            item = row_dict(row) or {}
            nid = int(item["id"])
            item["depth"] = depth_for(nid)
            item["selected"] = not selected_unplaced and not selected_favorites and nid == int(node_id or 0)
            item["path"] = path_cache.get(nid, "")
            item["direct_items"] = direct_counts.get(nid, 0)
            item["total_items"] = sum(direct_counts.get(i, 0) for i in desc_cache.get(nid, [nid]))
            tree.append(item)
        favorite_space_count = sum(1 for row in rows if int(row["is_favorite"] or 0))
        tree[1]["direct_items"] = favorite_space_count
        tree[1]["total_items"] = favorite_space_count

        selected_item_data = None
        if selected_item_type and selected_item_id and selected_item_type in visible:
            selected_item_data = inventory_item_by_id(conn, selected_item_type, selected_item_id)

        selected_validations = _validation_rows_for_item(conn, selected_item_data)

        if selected_unplaced:
            direct_items = unplaced_inventory_items(conn, visible_types=visible_types)
            unplaced_spaces = storage_child_items(conn, rows, direct_counts, 0, path_cache, desc_cache)
            unplaced_spaces = [item for item in unplaced_spaces if int(item["id"]) != DEFAULT_ROOT_STORAGE_NODE_ID]
            current_item = {
                "id": VIRTUAL_UNPLACED_NODE_ID,
                "parent_id": None,
                "name": "未归位",
                "path": "未归位",
                "rows": 1,
                "cols": 1,
                "grid_row": None,
                "grid_col": None,
                "is_virtual_unplaced": True,
            }
            return {
                "current": current_item,
                "grid": {"rows": 1, "cols": 1, "capacity": 1, "is_framed": False},
                "tree": tree,
                "children": unplaced_spaces,
                "frame_items": [],
                "direct_items": direct_items,
                "items": direct_items[:80],
                "selected_well": "",
                "selected_item": selected_item_data,
                "selected_validations": rows_list(selected_validations),
                "stats": {"nodes": len(rows), "children": len(unplaced_spaces), "direct": virtual_count, "total": virtual_count, "occupied": virtual_count + len(unplaced_spaces), "capacity": 1},
            }

        if selected_favorites:
            favorite_spaces = []
            for row in rows:
                if not int(row["is_favorite"] or 0):
                    continue
                item = row_dict(row) or {}
                nid = int(item["id"])
                item["path"] = path_cache.get(nid, "")
                item["children"] = len(conn.execute("SELECT id FROM storage_nodes WHERE parent_id = ?", (nid,)).fetchall())
                ids = desc_cache.get(nid, [nid])
                item["direct"] = direct_counts.get(nid, 0)
                item["total"] = sum(direct_counts.get(i, 0) for i in ids)
                item["direct_items"] = item["direct"]
                item["total_items"] = item["total"]
                item["is_unplaced"] = False
                item["grid_position"] = None
                item["grid_label"] = ""
                favorite_spaces.append(item)
            favorite_spaces.sort(key=lambda item: (int(item.get("favorite_sort_order") or 0), int(item.get("sort_order") or 0), str(item.get("name") or ""), int(item.get("id") or 0)))
            favorite_total = sum(int(item.get("total_items") or 0) for item in favorite_spaces)
            current_item = {
                "id": VIRTUAL_FAVORITES_NODE_ID,
                "parent_id": None,
                "name": "常用位置",
                "path": "常用位置",
                "rows": 1,
                "cols": 1,
                "grid_row": None,
                "grid_col": None,
                "is_virtual_favorites": True,
            }
            for item in tree:
                item["selected"] = is_virtual_favorites_id(item["id"])
            return {
                "current": current_item,
                "grid": {"rows": 1, "cols": 1, "capacity": 1, "is_framed": False},
                "tree": tree,
                "children": favorite_spaces,
                "frame_items": [],
                "direct_items": [],
                "items": favorite_spaces[:80],
                "selected_well": "",
                "selected_item": selected_item_data,
                "selected_validations": rows_list(selected_validations),
                "stats": {"nodes": len(rows), "children": len(favorite_spaces), "direct": 0, "total": favorite_total, "occupied": len(favorite_spaces), "capacity": max(1, len(favorite_spaces))},
            }

        if node_id is None:
            root = get_node(conn, DEFAULT_ROOT_STORAGE_NODE_ID)
            node_id = DEFAULT_ROOT_STORAGE_NODE_ID if root else None
        current = get_node(conn, node_id)
        if current is None:
            raise ApiError(404, "空间节点不存在")
        children = conn.execute(
            """
            SELECT * FROM storage_nodes
            WHERE parent_id = ? AND id > 0 AND COALESCE(node_type, 'space') != 'system'
            ORDER BY sort_order, name
            """,
            (node_id,),
        ).fetchall()
        direct_items = inventory_items_at_node(conn, node_id, direct_only=True, visible_types=visible_types)
        current_descendant_ids = desc_cache.get(node_id, [node_id])
        direct_item_count = direct_counts.get(node_id, 0)
        total_item_count = sum(direct_counts.get(i, 0) for i in current_descendant_ids)
        all_items = inventory_items_at_node(conn, node_id, limit=80, visible_types=visible_types)
        for item in tree:
            item["selected"] = int(item["id"]) == int(node_id or 0)

        current_grid_rows, current_grid_cols = default_grid_for_node(current["rows"], current["cols"])
        is_framed = not (current_grid_rows == 1 and current_grid_cols == 1)
        child_items = storage_child_items(conn, children, direct_counts, node_id, path_cache, desc_cache)
        positioned_children = [item for item in child_items if not item["is_unplaced"]]
        max_child_position = assign_grid_positions(positioned_children, current_grid_cols)
        frame_items = []
        if is_framed:
            frame_items = [item for item in direct_items if item.get("grid_cell")]

        selected_item = None
        if selected_well:
            selected_item = next((item for item in frame_items if item.get("grid_cell") == selected_well), None)

        if selected_item_data is None and selected_item:
            selected_item_data = inventory_item_by_id(conn, selected_item.get("item_type", "reagent"), int(selected_item["id"]))

        if not selected_validations:
            selected_validations = _validation_rows_for_item(conn, selected_item_data)

        grid_capacity = max(current_grid_rows * current_grid_cols, max_child_position)
        occupied_slots = len(child_items) + len(frame_items)
        current_item = row_dict(current) or {}
        current_item["path"] = path_cache.get(node_id, "")
        return {
            "current": current_item,
            "grid": {"rows": current_grid_rows, "cols": current_grid_cols, "capacity": grid_capacity, "is_framed": is_framed},
            "tree": tree,
            "children": child_items,
            "frame_items": frame_items,
            "direct_items": direct_items,
            "items": all_items,
            "selected_well": selected_well,
            "selected_item": selected_item_data,
            "selected_validations": rows_list(selected_validations),
            "stats": {"nodes": len(rows), "children": len(children), "direct": direct_item_count, "total": total_item_count, "occupied": occupied_slots, "capacity": grid_capacity},
        }


def _favorite_value(value: Any) -> int:
    return 1 if value is True or str(value).strip().lower() in {"1", "true", "yes", "on"} else 0


def create_storage_node(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ApiError(400, "空间名称不能为空")
    rows_value = clean_positive_int(data.get("rows"))
    cols_value = clean_positive_int(data.get("cols"))
    timestamp = now_text()
    with connect() as conn:
        parent_id = clean_optional_positive_int(data.get("parent_id"))
        validate_storage_parent(conn, parent_id)
        cur = conn.execute(
            """
            INSERT INTO storage_nodes
                (parent_id, name, node_type, space_type, location_code, rows, cols, grid_row, grid_col,
                 is_favorite, favorite_sort_order, note, sort_order, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, 'space', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parent_id,
                name,
                clean_space_type(data.get("space_type")),
                str(data.get("location_code", "")).strip() or None,
                rows_value,
                cols_value,
                clean_positive_int(data.get("grid_row")),
                clean_positive_int(data.get("grid_col")),
                _favorite_value(data.get("is_favorite")),
                clean_int_range(data.get("favorite_sort_order"), 0, 0, 100_000),
                str(data.get("note", "")).strip() or None,
                clean_int_range(data.get("sort_order"), 0, 0, 100_000),
                user["id"], user["id"], timestamp, timestamp,
            ),
        )
        create_audit(conn, user["id"], "api_create_storage_node", "storage_nodes", cur.lastrowid, data)
        conn.commit()
        row = conn.execute("SELECT * FROM storage_nodes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": row_dict(row)}


def clean_space_type(value: Any) -> int:
    try:
        return clean_space_type_code(value)
    except ValueError as exc:
        raise ApiError(400, "空间类型必须是 1 到 5") from exc


def _clear_out_of_bounds_grid_assignments(conn: Any, node: Any, user_id: int | None) -> dict[str, int]:
    node_id = int(node["id"])
    rows, cols = default_grid_for_node(node["rows"], node["cols"])
    timestamp = now_text()
    counts = {"storage_nodes": 0, "reagents": 0, "samples": 0}

    child_rows = conn.execute(
        """
        SELECT id FROM storage_nodes
        WHERE parent_id = ?
          AND grid_row IS NOT NULL
          AND grid_col IS NOT NULL
          AND (grid_row > ? OR grid_col > ?)
        """,
        (node_id, rows, cols),
    ).fetchall()
    child_ids = [int(row["id"]) for row in child_rows]
    if child_ids:
        placeholders = ",".join("?" for _ in child_ids)
        conn.execute(
            f"""
            UPDATE storage_nodes
            SET grid_row = NULL, grid_col = NULL, updated_by = ?, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [user_id, timestamp, *child_ids],
        )
        counts["storage_nodes"] = len(child_ids)

    allowed_positions = set(position_options_for_node(node))
    for table, key in (("reagents", "reagents"), ("clinical_samples", "samples")):
        base_params: list[Any] = [node_id]
        where = """
            storage_node_id = ?
            AND grid_cell IS NOT NULL
            AND TRIM(COALESCE(grid_cell, '')) != ''
        """
        if allowed_positions:
            placeholders = ",".join("?" for _ in allowed_positions)
            where += f" AND grid_cell NOT IN ({placeholders})"
            base_params.extend(sorted(allowed_positions))
        matching = conn.execute(f"SELECT id FROM {table} WHERE {where}", base_params).fetchall()
        ids = [int(row["id"]) for row in matching]
        if not ids:
            continue
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"""
            UPDATE {table}
            SET grid_cell = NULL, updated_by = ?, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [user_id, timestamp, *ids],
        )
        counts[key] = len(ids)
    return counts


def update_storage_node(node_id: int, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    allowed = ["parent_id", "name", "space_type", "location_code", "rows", "cols", "grid_row", "grid_col", "is_favorite", "favorite_sort_order", "note", "sort_order"]
    updates = {key: data[key] for key in allowed if key in data}
    if not updates:
        raise ApiError(400, "没有可更新字段")
    if "parent_id" in updates:
        updates["parent_id"] = clean_optional_positive_int(updates["parent_id"])
        if updates["parent_id"] == node_id:
            raise ApiError(400, "父级空间不能是自己")
    if "space_type" in updates:
        updates["space_type"] = clean_space_type(updates["space_type"])
    if "sort_order" in updates:
        updates["sort_order"] = clean_int_range(updates["sort_order"], 0, 0, 100_000)
    if "favorite_sort_order" in updates:
        updates["favorite_sort_order"] = clean_int_range(updates["favorite_sort_order"], 0, 0, 100_000)
    if "is_favorite" in updates:
        updates["is_favorite"] = _favorite_value(updates["is_favorite"])
    updates["updated_by"] = user["id"]
    updates["updated_at"] = now_text()
    with connect() as conn:
        old = get_node(conn, node_id)
        if old is None:
            raise ApiError(404, "空间节点不存在")
        final_parent_id = updates.get("parent_id", old["parent_id"])
        if final_parent_id and int(final_parent_id) in descendant_node_ids(conn, node_id, True):
            raise ApiError(400, "不能把空间移动到自己的下级")
        validate_storage_parent(conn, final_parent_id)
        if "rows" in updates:
            updates["rows"] = clean_positive_int(updates["rows"])
        if "cols" in updates:
            updates["cols"] = clean_positive_int(updates["cols"])
        if "grid_row" in updates:
            updates["grid_row"] = clean_positive_int(updates["grid_row"])
        if "grid_col" in updates:
            updates["grid_col"] = clean_positive_int(updates["grid_col"])
        final_parent_id = updates.get("parent_id", old["parent_id"])
        final_grid_row = updates.get("grid_row", old["grid_row"])
        final_grid_col = updates.get("grid_col", old["grid_col"])
        validate_storage_grid_target(conn, node_id, final_parent_id, final_grid_row, final_grid_col)
        old_parent_id = old["parent_id"]
        old_grid_row = old["grid_row"]
        old_grid_col = old["grid_col"]
        moved_space = (
            ("parent_id" in updates and updates["parent_id"] != old_parent_id)
            or ("grid_row" in updates and updates["grid_row"] != old_grid_row)
            or ("grid_col" in updates and updates["grid_col"] != old_grid_col)
        )
        from_snapshot = storage_node_position_snapshot(conn, old_parent_id, old_grid_row, old_grid_col) if moved_space else ""
        from_grid_label = storage_node_grid_label(conn, old_parent_id, old_grid_row, old_grid_col) if moved_space else None
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(f"UPDATE storage_nodes SET {assignments} WHERE id = ?", list(updates.values()) + [node_id])
        updated_node = get_node(conn, node_id)
        cleared = (
            _clear_out_of_bounds_grid_assignments(conn, updated_node, user["id"])
            if updated_node is not None and any(key in data for key in ("rows", "cols"))
            else {"storage_nodes": 0, "reagents": 0, "samples": 0}
        )

        for nid in descendant_node_ids(conn, node_id, True):
            refresh_inventory_locations_at_node(conn, nid)
        if moved_space:
            to_snapshot = storage_node_position_snapshot(conn, final_parent_id, final_grid_row, final_grid_col)
            to_grid_label = storage_node_grid_label(conn, final_parent_id, final_grid_row, final_grid_col)
            conn.execute(
                """
                INSERT INTO movements
                    (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
                     to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
                     moved_by, moved_at, reason, note)
                VALUES (?, ?, 'space', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "空间", str(node_id), node_id, old_parent_id or SYSTEM_UNPLACED_NODE_ID, from_grid_label, final_parent_id or SYSTEM_UNPLACED_NODE_ID, to_grid_label,
                    from_snapshot, to_snapshot, user["id"], now_text(),
                    MOVEMENT_REASON_SPACE_MOVE, f"{old['name']} 的上级或格位已调整",
                ),
            )
        audit_new_value = {**data, "cleared_out_of_bounds": cleared} if any(cleared.values()) else data
        create_audit(conn, user["id"], "api_update_storage_node", "storage_nodes", node_id, audit_new_value, row_dict(old))
        conn.commit()
        row = get_node(conn, node_id)
    return {"item": row_dict(row), "cleared_out_of_bounds": cleared}


def _clear_deleted_storage_history_references(conn: Any, deleted_ids: list[int]) -> dict[str, int]:
    placeholders = ",".join("?" for _ in deleted_ids)
    counts = {"movement_refs": 0}
    for column in ("from_storage_node_id", "to_storage_node_id"):
        counts["movement_refs"] += int(conn.execute(
            f"SELECT COUNT(*) AS n FROM movements WHERE {column} IN ({placeholders})",
            deleted_ids,
        ).fetchone()["n"] or 0)
        conn.execute(
            f"UPDATE movements SET {column} = ? WHERE {column} IN ({placeholders})",
            [SYSTEM_UNPLACED_NODE_ID, *deleted_ids],
        )
    return counts


def delete_storage_node(node_id: int, user: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        old = get_node(conn, node_id)
        if old is None:
            raise ApiError(404, "空间节点不存在")
        if int(old["id"]) <= 0 or str(old["node_type"] or "") == "system":
            raise ApiError(400, "系统状态节点不能删除")
        child_count = conn.execute(
            "SELECT COUNT(*) AS n FROM storage_nodes WHERE parent_id = ?",
            (node_id,),
        ).fetchone()["n"]
        if child_count:
            raise ApiError(400, f"该空间下还有 {child_count} 个下级空间，请先移动或删除下级空间")

        inventory_count = conn.execute(
            """
            SELECT SUM(n) AS n
            FROM (
                SELECT COUNT(*) AS n FROM reagents WHERE storage_node_id = ?
                UNION ALL
                SELECT COUNT(*) AS n FROM clinical_samples WHERE storage_node_id = ?
            )
            """,
            (node_id, node_id),
        ).fetchone()["n"] or 0
        if inventory_count:
            raise ApiError(400, f"该空间内还有 {inventory_count} 件库存，请先移动或出库")

        top_level_count = conn.execute(
            """
            SELECT COUNT(*) AS n FROM storage_nodes
            WHERE parent_id IS NULL AND id > 0 AND COALESCE(node_type, 'space') != 'system'
            """
        ).fetchone()["n"]
        if old["parent_id"] is None and top_level_count <= 1:
            raise ApiError(400, "不能删除唯一的顶层空间")

        next_node_id = old["parent_id"]
        if next_node_id is None:
            next_node = conn.execute(
                """
                SELECT id FROM storage_nodes
                WHERE id != ?
                  AND id > 0
                  AND COALESCE(node_type, 'space') != 'system'
                ORDER BY COALESCE(parent_id, 0), sort_order, name
                LIMIT 1
                """,
                (node_id,),
            ).fetchone()
            next_node_id = next_node["id"] if next_node else None

        deleted_ids = [node_id]
        reference_counts = _clear_deleted_storage_history_references(conn, deleted_ids)
        placeholders = ",".join("?" for _ in deleted_ids)
        conn.execute(f"DELETE FROM storage_nodes WHERE id IN ({placeholders})", deleted_ids)
        create_audit(
            conn,
            user["id"],
            "api_delete_storage_node",
            "storage_nodes",
            node_id,
            {"deleted_ids": deleted_ids, "cleared_history_refs": reference_counts},
            row_dict(old),
        )
        conn.commit()
    return {"ok": True, "deleted_id": node_id, "deleted_ids": deleted_ids, "next_node_id": next_node_id, "cleared_history_refs": reference_counts}
