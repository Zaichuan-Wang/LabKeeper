from __future__ import annotations

from typing import Any

from core.common import ApiError, create_audit, now_text, row_dict, rows_list
from core.constants import NODE_TYPE_LABELS
from db.database import connect
from services.storage_inventory import (
    assign_grid_positions,
    batch_node_paths_and_descendants,
    clean_node_dimension,
    clean_positive_int,
    coord_list,
    default_grid_for_node,
    descendant_node_ids,
    get_node,
    grid_label,
    find_position_owner,
    inventory_item_by_id,
    inventory_items_at_node,
    node_full_path,
    occupied_positions,
    refresh_inventory_locations_at_node,
    storage_item_counts,
    storage_location_text,
    unplaced_inventory_items,
    unplaced_item_count,
    validate_storage_parent,
)


VIRTUAL_UNPLACED_NODE_ID = -1
DEFAULT_ROOT_STORAGE_NODE_ID = 1


def is_virtual_unplaced_id(node_id: Any) -> bool:
    try:
        return int(node_id) == VIRTUAL_UNPLACED_NODE_ID
    except (TypeError, ValueError):
        return False


def storage_node_position_snapshot(conn: Any, parent_id: int | None, grid_row: Any, grid_col: Any) -> str:
    if not parent_id:
        return "未归位"
    parent = get_node(conn, parent_id)
    if parent is None:
        return ""
    position = None
    if grid_row and grid_col:
        _, cols = default_grid_for_node(str(parent["node_type"]), parent["rows"], parent["cols"])
        position = grid_label((int(grid_row) - 1) * int(cols or 1) + int(grid_col), int(cols or 1))
    return storage_location_text(conn, int(parent_id), position)


def storage_node_grid_label(conn: Any, parent_id: int | None, grid_row: Any, grid_col: Any) -> str | None:
    if not parent_id or not (grid_row and grid_col):
        return None
    parent = get_node(conn, parent_id)
    if parent is None:
        return None
    _, cols = default_grid_for_node(str(parent["node_type"]), parent["rows"], parent["cols"])
    return grid_label((int(grid_row) - 1) * int(cols or 1) + int(grid_col), int(cols or 1))


def validate_storage_grid_target(conn: Any, node_id: int, parent_id: int | None, grid_row: Any, grid_col: Any) -> None:
    if not parent_id or not (grid_row and grid_col):
        return
    parent = get_node(conn, parent_id)
    if parent is None:
        return
    _, cols = default_grid_for_node(str(parent["node_type"]), parent["rows"], parent["cols"])
    label = grid_label((int(grid_row) - 1) * int(cols or 1) + int(grid_col), int(cols or 1))
    sibling = conn.execute(
        """
        SELECT id, name FROM storage_nodes
        WHERE parent_id = ? AND grid_row = ? AND grid_col = ? AND id <> ?
        LIMIT 1
        """,
        (parent_id, grid_row, grid_col, node_id),
    ).fetchone()
    if sibling:
        raise ApiError(409, f"格位 {label} 已被 {sibling['name']} 占用")
    existing = find_position_owner(conn, parent_id, label)
    if existing:
        raise ApiError(409, f"格位 {label} 已被 {existing['code']} · {existing['name']} 占用")


def storage_tree() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT n.*, p.name AS parent_name
            FROM storage_nodes n LEFT JOIN storage_nodes p ON p.id = n.parent_id
            ORDER BY COALESCE(n.parent_id, 0), n.sort_order, n.name
            """
        ).fetchall()
        counts = storage_item_counts(conn)
        path_cache, desc_cache = batch_node_paths_and_descendants(conn)
        items = []
        for row in rows:
            item = row_dict(row) or {}
            nid = int(item["id"])
            item["type_label"] = NODE_TYPE_LABELS.get(item["node_type"], item["node_type"])
            item["path"] = path_cache.get(nid, "")
            item["direct_items"] = counts.get(nid, 0)
            item["total_items"] = sum(counts.get(i, 0) for i in desc_cache.get(nid, [nid]))
            items.append(item)
    return {"items": items, "count": len(items)}


def storage_child_items(conn: Any, rows: list[Any], direct_counts: dict[int, int], node_id: int, path_cache: dict[int, str] | None = None, desc_cache: dict[int, list[int]] | None = None) -> list[dict[str, Any]]:
    child_items = []
    for row in rows:
        if int(row["parent_id"] or 0) != int(node_id):
            continue
        item = row_dict(row) or {}
        nid = int(item["id"])
        item["type_label"] = NODE_TYPE_LABELS.get(item["node_type"], item["node_type"])
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


def storage_visual(
    node_id: int | None = None,
    selected_well: str = "",
    selected_item_type: str = "",
    selected_item_id: int | None = None,
) -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM storage_nodes ORDER BY COALESCE(parent_id, 0), sort_order, name").fetchall()
        direct_counts = storage_item_counts(conn)
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

        selected_virtual = is_virtual_unplaced_id(node_id)
        virtual_count = unplaced_item_count(conn)
        tree = [{
            "id": VIRTUAL_UNPLACED_NODE_ID,
            "parent_id": None,
            "name": "未归位",
            "node_type": "unplaced",
            "type_label": "未归位",
            "path": "未归位",
            "depth": 0,
            "selected": selected_virtual,
            "direct_items": virtual_count,
            "total_items": virtual_count,
            "is_virtual_unplaced": True,
        }]
        for row in rows:
            item = row_dict(row) or {}
            nid = int(item["id"])
            item["type_label"] = NODE_TYPE_LABELS.get(item["node_type"], item["node_type"])
            item["depth"] = depth_for(nid)
            item["selected"] = not selected_virtual and nid == int(node_id or 0)
            item["path"] = path_cache.get(nid, "")
            item["direct_items"] = direct_counts.get(nid, 0)
            item["total_items"] = sum(direct_counts.get(i, 0) for i in desc_cache.get(nid, [nid]))
            tree.append(item)

        selected_item_data = None
        if selected_item_type and selected_item_id:
            selected_item_data = inventory_item_by_id(conn, selected_item_type, selected_item_id)

        selected_validations = []
        if selected_item_data and selected_item_data.get("item_type") == "reagent":
            catalog_no = str(selected_item_data.get("catalog_no") or "").strip()
            selected_validations = conn.execute(
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

        if selected_virtual:
            direct_items = unplaced_inventory_items(conn)
            unplaced_spaces = storage_child_items(conn, rows, direct_counts, 0, path_cache, desc_cache)
            unplaced_spaces = [item for item in unplaced_spaces if int(item["id"]) != DEFAULT_ROOT_STORAGE_NODE_ID]
            current_item = {
                "id": VIRTUAL_UNPLACED_NODE_ID,
                "parent_id": None,
                "name": "未归位",
                "node_type": "unplaced",
                "type_label": "未归位",
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
                "wells": [],
                "direct_items": direct_items,
                "items": direct_items[:80],
                "selected_well": "",
                "selected_item": selected_item_data,
                "selected_validations": rows_list(selected_validations),
                "stats": {"nodes": len(rows), "children": len(unplaced_spaces), "direct": virtual_count, "total": virtual_count, "occupied": virtual_count + len(unplaced_spaces), "capacity": 1},
            }

        if node_id is None:
            root = get_node(conn, DEFAULT_ROOT_STORAGE_NODE_ID)
            node_id = DEFAULT_ROOT_STORAGE_NODE_ID if root else None
        current = get_node(conn, node_id)
        if current is None:
            raise ApiError(404, "空间节点不存在")
        children = conn.execute("SELECT * FROM storage_nodes WHERE parent_id = ? ORDER BY sort_order, name", (node_id,)).fetchall()
        direct_items = inventory_items_at_node(conn, node_id, direct_only=True)
        current_descendant_ids = desc_cache.get(node_id, [node_id])
        direct_item_count = direct_counts.get(node_id, 0)
        total_item_count = sum(direct_counts.get(i, 0) for i in current_descendant_ids)
        all_items = inventory_items_at_node(conn, node_id, limit=80)
        for item in tree:
            item["selected"] = int(item["id"]) == int(node_id or 0)

        current_grid_rows, current_grid_cols = default_grid_for_node(current["node_type"], current["rows"], current["cols"])
        is_framed = current["node_type"] == "box" or not (current_grid_rows == 1 and current_grid_cols == 1)
        child_items = storage_child_items(conn, children, direct_counts, node_id, path_cache, desc_cache)
        positioned_children = [item for item in child_items if not item["is_unplaced"]]
        max_child_position = assign_grid_positions(positioned_children, current_grid_cols)
        frame_items = []
        if current["node_type"] != "box" and is_framed:
            frame_items = [item for item in direct_items if item.get("position_in_box")]

        wells = []
        selected_item = None
        if current["node_type"] == "box":
            rows_count = int(current["rows"] or 9)
            cols_count = int(current["cols"] or 9)
            occupied = occupied_positions(conn, node_id)
            for coord in coord_list(rows_count, cols_count):
                item = occupied.get(coord)
                if coord == selected_well:
                    selected_item = item
                wells.append({"coord": coord, "occupied": bool(item), "selected": coord == selected_well, "item": item})
        elif selected_well:
            selected_item = next((item for item in frame_items if item.get("position_in_box") == selected_well), None)

        if selected_item_data is None and selected_item:
            selected_item_data = inventory_item_by_id(conn, selected_item.get("item_type", "reagent"), int(selected_item["id"]))

        if not selected_validations and selected_item_data and selected_item_data.get("item_type") == "reagent":
            catalog_no = str(selected_item_data.get("catalog_no") or "").strip()
            selected_validations = conn.execute(
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

        grid_capacity = max(current_grid_rows * current_grid_cols, max_child_position)
        occupied_slots = sum(1 for well in wells if well["occupied"]) if wells else len(child_items) + len(frame_items)
        current_item = row_dict(current) or {}
        current_item["type_label"] = NODE_TYPE_LABELS.get(current["node_type"], current["node_type"])
        current_item["path"] = path_cache.get(node_id, "")
        return {
            "current": current_item,
            "grid": {"rows": current_grid_rows, "cols": current_grid_cols, "capacity": grid_capacity, "is_framed": is_framed},
            "tree": tree,
            "children": child_items,
            "frame_items": frame_items,
            "wells": wells,
            "direct_items": direct_items,
            "items": all_items,
            "selected_well": selected_well,
            "selected_item": selected_item_data,
            "selected_validations": rows_list(selected_validations),
            "stats": {"nodes": len(rows), "children": len(children), "direct": direct_item_count, "total": total_item_count, "occupied": occupied_slots, "capacity": len(wells) if wells else grid_capacity},
        }


def create_storage_node(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    node_type = str(data.get("node_type", "space")).strip() or "space"
    if not name:
        raise ApiError(400, "空间名称不能为空")
    if node_type not in NODE_TYPE_LABELS:
        raise ApiError(400, "空间类型不正确")
    rows_value = clean_node_dimension(node_type, "rows", data.get("rows"))
    cols_value = clean_node_dimension(node_type, "cols", data.get("cols"))
    timestamp = now_text()
    with connect() as conn:
        parent_id = int(data.get("parent_id") or 0) or None
        validate_storage_parent(conn, node_type, parent_id)
        cur = conn.execute(
            """
            INSERT INTO storage_nodes
                (parent_id, name, node_type, location_code, rows, cols, grid_row, grid_col, note, sort_order, created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parent_id,
                name,
                node_type,
                str(data.get("location_code", "")).strip() or None,
                rows_value,
                cols_value,
                clean_positive_int(data.get("grid_row")),
                clean_positive_int(data.get("grid_col")),
                str(data.get("note", "")).strip() or None,
                int(data.get("sort_order") or 0),
                user["id"], user["id"], timestamp, timestamp,
            ),
        )
        create_audit(conn, user["id"], "api_create_storage_node", "storage_nodes", cur.lastrowid, data)
        conn.commit()
        row = conn.execute("SELECT * FROM storage_nodes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": row_dict(row)}


def update_storage_node(node_id: int, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    allowed = ["parent_id", "name", "node_type", "location_code", "rows", "cols", "grid_row", "grid_col", "note", "sort_order"]
    updates = {key: data[key] for key in allowed if key in data}
    if not updates:
        raise ApiError(400, "没有可更新字段")
    if "node_type" in updates and updates["node_type"] not in NODE_TYPE_LABELS:
        raise ApiError(400, "空间类型不正确")
    if "parent_id" in updates:
        updates["parent_id"] = int(updates["parent_id"] or 0) or None
        if updates["parent_id"] == node_id:
            raise ApiError(400, "父级空间不能是自己")
    updates["updated_by"] = user["id"]
    updates["updated_at"] = now_text()
    with connect() as conn:
        old = get_node(conn, node_id)
        if old is None:
            raise ApiError(404, "空间节点不存在")
        final_type = updates.get("node_type", old["node_type"])
        final_parent_id = updates.get("parent_id", old["parent_id"])
        if final_parent_id and int(final_parent_id) in descendant_node_ids(conn, node_id, True):
            raise ApiError(400, "不能把空间移动到自己的下级")
        validate_storage_parent(conn, final_type, final_parent_id)
        if "rows" in updates:
            updates["rows"] = clean_node_dimension(final_type, "rows", updates["rows"])
        if "cols" in updates:
            updates["cols"] = clean_node_dimension(final_type, "cols", updates["cols"])
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

        for nid in descendant_node_ids(conn, node_id, True):
            refresh_inventory_locations_at_node(conn, nid)
        if moved_space:
            to_snapshot = storage_node_position_snapshot(conn, final_parent_id, final_grid_row, final_grid_col)
            to_grid_label = storage_node_grid_label(conn, final_parent_id, final_grid_row, final_grid_col)
            conn.execute(
                """
                INSERT INTO movements
                    (object_type, object_id, item_type, item_id, from_storage_node_id, from_position_in_box,
                     to_storage_node_id, to_position_in_box, from_location_snapshot, to_location_snapshot,
                     moved_by, moved_at, reason, note)
                VALUES (?, ?, 'space', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "空间", str(node_id), node_id, old_parent_id, from_grid_label, final_parent_id, to_grid_label,
                    from_snapshot, to_snapshot, user["id"], now_text(),
                    "空间移动", f"{old['name']} 的上级或格位已调整",
                ),
            )
        create_audit(conn, user["id"], "api_update_storage_node", "storage_nodes", node_id, data, row_dict(old))
        conn.commit()
        row = get_node(conn, node_id)
    return {"item": row_dict(row)}


def _record_unplaced_moves_for_deleted_storage(
    conn: Any, deleted_ids: list[int], user: dict[str, Any], timestamp: str, spec: tuple[str, str, str],
) -> int:
    table, code_column, object_type = spec
    placeholders = ",".join("?" for _ in deleted_ids)
    rows = conn.execute(
        f"SELECT id, {code_column} AS object_code, storage_node_id, position_in_box FROM {table} WHERE storage_node_id IN ({placeholders})",
        deleted_ids,
    ).fetchall()
    for row in rows:
        item_id = int(row["id"])
        item_type = "reagent" if object_type == "试剂" else "sample"
        from_location = storage_location_text(conn, int(row["storage_node_id"]), row["position_in_box"])
        conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_position_in_box,
                 to_storage_node_id, to_position_in_box, from_location_snapshot, to_location_snapshot,
                 moved_by, moved_at, reason, note)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_type, row["object_code"] or str(item_id), item_type, item_id,
                row["storage_node_id"], row["position_in_box"], from_location, "未归位",
                user["id"], timestamp, "原空间删除，转入未归位", "系统自动迁移当前位置，历史快照不改。",
            ),
        )
    return len(rows)


def _repoint_deleted_storage_references(conn: Any, deleted_ids: list[int], user: dict[str, Any]) -> dict[str, int]:
    placeholders = ",".join("?" for _ in deleted_ids)
    timestamp = now_text()
    counts = {"reagents": 0, "clinical_samples": 0, "arrivals": 0, "movement_refs": 0}

    for key, spec in {
        "reagents": ("reagents", "code", "试剂"),
        "clinical_samples": ("clinical_samples", "code", "临床标本"),
    }.items():
        counts[key] = _record_unplaced_moves_for_deleted_storage(conn, deleted_ids, user, timestamp, spec)

    conn.execute(
        f"UPDATE reagents SET storage_node_id = NULL, position_in_box = NULL, updated_by = ?, updated_at = ? WHERE storage_node_id IN ({placeholders})",
        [user["id"], timestamp, *deleted_ids],
    )
    conn.execute(
        f"UPDATE clinical_samples SET storage_node_id = NULL, position_in_box = NULL, updated_by = ?, updated_at = ? WHERE storage_node_id IN ({placeholders})",
        [user["id"], timestamp, *deleted_ids],
    )
    counts["arrivals"] = conn.execute(
        f"SELECT COUNT(*) AS n FROM arrivals WHERE storage_node_id IN ({placeholders})",
        deleted_ids,
    ).fetchone()["n"]
    conn.execute(
        f"UPDATE arrivals SET storage_node_id = NULL, position_in_box = NULL, location_snapshot = COALESCE(NULLIF(location_snapshot, ''), '未归位') WHERE storage_node_id IN ({placeholders})",
        deleted_ids,
    )
    for column in ("from_storage_node_id", "to_storage_node_id"):
        counts["movement_refs"] += conn.execute(
            f"SELECT COUNT(*) AS n FROM movements WHERE {column} IN ({placeholders})",
            deleted_ids,
        ).fetchone()["n"]
        conn.execute(
            f"UPDATE movements SET {column} = NULL WHERE {column} IN ({placeholders})",
            deleted_ids,
        )
    return counts


def delete_storage_node(node_id: int, user: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        old = get_node(conn, node_id)
        if old is None:
            raise ApiError(404, "空间节点不存在")
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
            WHERE parent_id IS NULL
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
                ORDER BY COALESCE(parent_id, 0), sort_order, name
                LIMIT 1
                """,
                (node_id,),
            ).fetchone()
            next_node_id = next_node["id"] if next_node else None

        deleted_ids = [node_id]
        reference_counts = _repoint_deleted_storage_references(conn, deleted_ids, user)
        placeholders = ",".join("?" for _ in deleted_ids)
        conn.execute(f"DELETE FROM storage_nodes WHERE id IN ({placeholders})", deleted_ids)
        create_audit(
            conn,
            user["id"],
            "api_delete_storage_node",
            "storage_nodes",
            node_id,
            {"deleted_ids": deleted_ids, "repointed": reference_counts},
            row_dict(old),
        )
        conn.commit()
    return {"ok": True, "deleted_id": node_id, "deleted_ids": deleted_ids, "next_node_id": next_node_id, "repointed": reference_counts}
