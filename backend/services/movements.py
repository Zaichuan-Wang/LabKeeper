from __future__ import annotations

from typing import Any

from core.common import ApiError, clean_optional_positive_int, create_audit, now_text, row_dict, rows_list
from core.constants import STATUS_CONSUMED
from db.database import connect
from services.storage_inventory import (
    assign_reagent_to_node,
    assign_sample_to_node,
    default_grid_for_node,
    descendant_node_ids,
    find_position_owner,
    get_node,
    grid_label,
    refresh_inventory_locations_at_node,
    release_sample_storage,
    occupies_storage,
    storage_location_text,
    validate_storage_parent,
)


def sample_object_id(sample: Any) -> str:
    source = sample["code"] or str(sample["id"])
    return str(source)


def row_location_snapshot(conn: Any, row: Any) -> str:
    node_id = row["storage_node_id"]
    if not node_id:
        if "code" in row.keys():
            return "未归位" if occupies_storage(row["status"]) else ""
        return "未归位" if occupies_storage(row["status"]) else ""
    return storage_location_text(conn, int(node_id), str(row["grid_cell"] or "").strip() or None)


def movement_item(row: Any) -> dict[str, Any]:
    item = row_dict(row) or {}
    item["from_location"] = item.get("from_location_snapshot") or ""
    item["to_location"] = item.get("to_location_snapshot") or ""
    reason = str(item.get("reason") or "")
    item["can_rollback"] = bool(
        item.get("id")
        and item.get("reverted_by_movement_id") is None
        and item.get("object_type") in {"试剂", "临床标本", "空间"}
        and (item.get("object_type") != "临床标本" or item.get("item_id"))
        and not reason.startswith("回滚")
    )
    return item


def same_storage_position(row: Any, node_id: Any, position: Any) -> bool:
    return int(row["storage_node_id"] or 0) == int(node_id or 0) and str(row["grid_cell"] or "").strip() == str(position or "").strip()


def _load_movable_item(conn: Any, item_type: str, item_id: int, action_label: str) -> tuple[Any, str, str]:
    if item_type == "sample":
        item = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (item_id,)).fetchone()
        if item is None:
            raise ApiError(404, "临床标本不存在")
        if not occupies_storage(item["status"]):
            raise ApiError(409, f"只有已入库标本可以{action_label}")
        return item, "临床标本", sample_object_id(item)
    item = conn.execute("SELECT * FROM reagents WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise ApiError(404, "试剂不存在")
    if not occupies_storage(item["status"]):
        raise ApiError(409, f"只有已入库试剂可以{action_label}")
    return item, "试剂", item["code"] or str(item_id)


def grid_row_col_from_label(conn: Any, parent_id: int | None, label: str | None) -> tuple[int | None, int | None]:
    clean = str(label or "").strip()
    if not parent_id or not clean:
        return None, None
    parent = get_node(conn, parent_id)
    if parent is None:
        return None, None
    rows, cols = default_grid_for_node(parent["rows"], parent["cols"])
    for row in range(1, rows + 1):
        for col in range(1, cols + 1):
            if grid_label((row - 1) * cols + col, cols) == clean:
                return row, col
    return None, None


def storage_node_location_snapshot(conn: Any, parent_id: int | None, position: str | None) -> str:
    if not parent_id:
        return "未归位"
    return storage_location_text(conn, int(parent_id), str(position or "").strip() or None)


def validate_space_rollback_target(conn: Any, node_id: int, parent_id: int | None, grid_row: int | None, grid_col: int | None) -> None:
    node = get_node(conn, node_id)
    if node is None:
        raise ApiError(404, "空间节点不存在")
    if parent_id and int(parent_id) in descendant_node_ids(conn, node_id, True):
        raise ApiError(400, "不能把空间回滚到自己的下级")
    validate_storage_parent(conn, parent_id)
    if not parent_id or not (grid_row and grid_col):
        return
    sibling = conn.execute(
        """
        SELECT id, name FROM storage_nodes
        WHERE parent_id = ? AND grid_row = ? AND grid_col = ? AND id <> ?
        LIMIT 1
        """,
        (parent_id, grid_row, grid_col, node_id),
    ).fetchone()
    parent = get_node(conn, parent_id)
    _, cols = default_grid_for_node(parent["rows"], parent["cols"]) if parent else (1, 1)
    label = grid_label((grid_row - 1) * int(cols or 1) + grid_col, int(cols or 1))
    if sibling:
        raise ApiError(409, f"原格位 {label} 已被 {sibling['name']} 占用，不能回滚")
    existing = find_position_owner(conn, parent_id, label)
    if existing:
        raise ApiError(409, f"原格位 {label} 已被 {existing['code']} · {existing['name']} 占用，不能回滚")


def list_movements() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.*, m.from_location_snapshot AS from_location, m.to_location_snapshot AS to_location,
                   u.display_name AS moved_by_name
            FROM movements m LEFT JOIN users u ON u.id = m.moved_by
            WHERE COALESCE(m.to_location_snapshot, '') <> '已出库'
            ORDER BY m.moved_at DESC LIMIT 200
            """
        ).fetchall()
    items = [movement_item(row) for row in rows]
    return {"items": items, "count": len(items)}


def create_movement(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    item_type = str(data.get("item_type", "reagent")).strip() or "reagent"
    item_id = clean_optional_positive_int(data.get("item_id")) or 0
    to_node_id = clean_optional_positive_int(data.get("to_storage_node_id")) or 0
    if item_type not in {"reagent", "sample"}:
        raise ApiError(400, "移动类型不正确")
    if not item_id:
        raise ApiError(400, "必须选择库存")
    position = str(data.get("grid_cell", "")).strip() or None
    timestamp = now_text()
    with connect() as conn:
        to_node_id = to_node_id or None
        position = position if to_node_id else None
        item, object_type, object_id = _load_movable_item(conn, item_type, item_id, "移动")
        from_node_id = item["storage_node_id"]
        from_position = str(item["grid_cell"] or "").strip() or None
        from_location = row_location_snapshot(conn, item)
        if same_storage_position(item, to_node_id, position):
            return {"item": {
                "id": None,
                "object_type": object_type,
                "object_id": object_id,
                "item_type": item_type,
                "item_id": item_id,
                "from_storage_node_id": from_node_id,
                "from_grid_cell": from_position,
                "to_storage_node_id": from_node_id,
                "to_grid_cell": from_position,
                "from_location": from_location,
                "to_location": from_location,
                "reason": str(data.get("reason", "")).strip(),
                "note": str(data.get("note", "")).strip(),
                "unchanged": True,
                "can_rollback": False,
            }}
        if item_type == "sample":
            assign_sample_to_node(conn, item_id, to_node_id, user["id"], position)
            updated = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (item_id,)).fetchone()
            to_location = row_location_snapshot(conn, updated)
            object_id = sample_object_id(updated)
        else:
            assign_reagent_to_node(conn, item_id, to_node_id, user["id"], position)
            updated = conn.execute("SELECT * FROM reagents WHERE id = ?", (item_id,)).fetchone()
            to_location = row_location_snapshot(conn, updated)
            object_id = updated["code"] or str(item_id)
        cur = conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
                 to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
                 moved_by, moved_at, reason, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_type, object_id, item_type, item_id,
                from_node_id, from_position, to_node_id, position, from_location, to_location, user["id"], timestamp,
                str(data.get("reason", "")).strip(), str(data.get("note", "")).strip(),
            ),
        )
        create_audit(conn, user["id"], "api_create_movement", "movements", cur.lastrowid, data)
        conn.commit()
        row = conn.execute("SELECT * FROM movements WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": movement_item(row)}


def rollback_movement(movement_id: int, user: dict[str, Any]) -> dict[str, Any]:
    timestamp = now_text()
    with connect() as conn:
        movement = conn.execute("SELECT * FROM movements WHERE id = ?", (movement_id,)).fetchone()
        if movement is None:
            raise ApiError(404, "移动记录不存在")
        if movement["reverted_by_movement_id"] is not None:
            raise ApiError(409, "这条移动记录已经回滚过")
        if str(movement["reason"] or "").startswith("回滚"):
            raise ApiError(409, "回滚记录不能再次回滚")

        object_type = str(movement["object_type"] or "")
        from_node_id = movement["from_storage_node_id"]
        from_position = str(movement["from_grid_cell"] or "").strip() or None
        to_node_id = movement["to_storage_node_id"]
        to_position = str(movement["to_grid_cell"] or "").strip() or None

        if object_type == "试剂":
            reagent_id = int(movement["item_id"] or 0)
            if not reagent_id:
                raise ApiError(409, "旧移动记录缺少试剂 ID，不能自动回滚")
            item = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
            if item is None:
                raise ApiError(404, "试剂不存在")
            if not occupies_storage(item["status"]):
                raise ApiError(409, "只有已入库试剂可以回滚移动")
            if not same_storage_position(item, to_node_id, to_position):
                raise ApiError(409, "该试剂已经不在这条记录的新位置，不能回滚")
            current_location = row_location_snapshot(conn, item)
            assign_reagent_to_node(conn, reagent_id, int(from_node_id or 0) or None, user["id"], from_position)
            updated = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
            target_location = row_location_snapshot(conn, updated)
            rollback_type = "试剂"
            rollback_object_id = updated["code"] or str(reagent_id)
            rollback_item_type = "reagent"
            rollback_item_id = reagent_id

        elif object_type == "临床标本":
            sample_id = int(movement["item_id"] or 0)
            if not sample_id:
                raise ApiError(409, "旧移动记录缺少标本 ID，不能自动回滚")
            sample = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
            if sample is None:
                raise ApiError(404, "临床标本不存在")
            if not occupies_storage(sample["status"]):
                raise ApiError(409, "只有已入库标本可以回滚移动")
            if not same_storage_position(sample, to_node_id, to_position):
                raise ApiError(409, "该标本已经不在这条记录的新位置，不能回滚")
            current_location = row_location_snapshot(conn, sample)
            assign_sample_to_node(conn, int(sample["id"]), int(from_node_id or 0) or None, user["id"], from_position)
            updated = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample["id"],)).fetchone()
            target_location = row_location_snapshot(conn, updated)
            rollback_type = "临床标本"
            rollback_object_id = sample_object_id(updated)
            rollback_item_type = "sample"
            rollback_item_id = int(sample["id"])

        elif object_type == "空间":
            node_id = int(str(movement["object_id"] or "0"))
            node = get_node(conn, node_id)
            if node is None:
                raise ApiError(404, "空间节点不存在")
            if int(node["parent_id"] or 0) != int(to_node_id or 0):
                raise ApiError(409, "该空间已经不在这条记录的新上级，不能回滚")
            expected_row, expected_col = grid_row_col_from_label(conn, int(to_node_id or 0) or None, to_position)
            if (expected_row or expected_col) and (int(node["grid_row"] or 0) != int(expected_row or 0) or int(node["grid_col"] or 0) != int(expected_col or 0)):
                raise ApiError(409, "该空间已经不在这条记录的新格位，不能回滚")
            if not to_position and (node["grid_row"] or node["grid_col"]):
                raise ApiError(409, "该空间已经不在这条记录的新位置，不能回滚")
            target_row, target_col = grid_row_col_from_label(conn, int(from_node_id or 0) or None, from_position)
            if from_position and not (target_row and target_col):
                raise ApiError(409, "原格位已不在当前空间框架内，不能回滚")
            validate_space_rollback_target(conn, node_id, int(from_node_id or 0) or None, target_row, target_col)
            current_location = storage_node_location_snapshot(conn, int(to_node_id or 0) or None, to_position)
            target_location = storage_node_location_snapshot(conn, int(from_node_id or 0) or None, from_position)
            conn.execute(
                """
                UPDATE storage_nodes
                SET parent_id = ?, grid_row = ?, grid_col = ?, updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(from_node_id or 0) or None, target_row, target_col, user["id"], timestamp, node_id),
            )
            for nid in descendant_node_ids(conn, node_id, True):
                refresh_inventory_locations_at_node(conn, nid)
            rollback_type = "空间"
            rollback_object_id = str(node_id)
            rollback_item_type = "space"
            rollback_item_id = node_id

        else:
            raise ApiError(409, "这类移动记录暂不支持回滚")

        cur = conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
                 to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
                 moved_by, moved_at, reason, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rollback_type, rollback_object_id, rollback_item_type, rollback_item_id,
                to_node_id, to_position, from_node_id, from_position,
                current_location, target_location, user["id"], timestamp,
                "回滚移动", f"回滚移动记录 #{movement_id}",
            ),
        )
        conn.execute(
            "UPDATE movements SET reverted_by_movement_id = ? WHERE id = ?",
            (cur.lastrowid, movement_id),
        )
        create_audit(conn, user["id"], "api_rollback_movement", "movements", movement_id, {"rollback_movement_id": cur.lastrowid}, row_dict(movement))
        conn.commit()
        row = conn.execute("SELECT * FROM movements WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": movement_item(row)}


def list_checkouts() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.*, m.from_location_snapshot AS from_location, m.to_location_snapshot AS to_location,
                   u.display_name AS moved_by_name
            FROM movements m LEFT JOIN users u ON u.id = m.moved_by
            WHERE m.to_location_snapshot = '已出库'
            ORDER BY m.moved_at DESC LIMIT 200
            """
        ).fetchall()
    return {"items": rows_list(rows), "count": len(rows)}


def create_checkout(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    item_type = str(data.get("item_type", "reagent")).strip() or "reagent"
    item_id = clean_optional_positive_int(data.get("item_id")) or 0
    if item_type not in {"reagent", "sample"}:
        raise ApiError(400, "出库类型不正确")
    if not item_id:
        raise ApiError(400, "必须选择出库库存")
    reason = str(data.get("reason", "出库")).strip() or "出库"
    note = str(data.get("note", "")).strip()
    timestamp = now_text()
    with connect() as conn:
        item, object_type, object_id = _load_movable_item(conn, item_type, item_id, "出库")
        from_node_id = item["storage_node_id"]
        from_position = str(item["grid_cell"] or "").strip() or None
        from_location = row_location_snapshot(conn, item) or "未放置"
        if item_type == "sample":
            conn.execute(
                """
                UPDATE clinical_samples
                SET status = ?, updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (STATUS_CONSUMED, user["id"], timestamp, item_id),
            )
            release_sample_storage(conn, item_id, user["id"])
        else:
            conn.execute(
                """
                UPDATE reagents
                SET status = ?, quantity = 0, updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (STATUS_CONSUMED, user["id"], timestamp, item_id),
            )
            assign_reagent_to_node(conn, item_id, None, user["id"])
        cur = conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
                 to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
                 moved_by, moved_at, reason, note)
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, '已出库', ?, ?, ?, ?)
            """,
            (object_type, object_id, item_type, item_id, from_node_id, from_position, from_location, user["id"], timestamp, reason, note),
        )
        create_audit(conn, user["id"], "api_create_checkout", "movements", cur.lastrowid, data)
        conn.commit()
        row = conn.execute("SELECT * FROM movements WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": movement_item(row)}
