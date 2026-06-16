from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core.common import ApiError, clean_optional_positive_int, create_audit, now_text, row_dict, rows_list
from core.constants import (
    MOVEMENT_REASON_ARRIVAL,
    MOVEMENT_REASON_CHECKOUT,
    MOVEMENT_REASON_MOVE,
    MOVEMENT_REASON_SPACE_MOVE,
    SYSTEM_CHECKED_OUT_NODE_ID,
    SYSTEM_UNPLACED_NODE_ID,
    STATUS_CONSUMED,
)
from db.database import connect
from services.options_config import load_dropdown_options
from services.storage_inventory import (
    assign_reagent_to_node,
    assign_sample_to_node,
    occupies_storage,
    storage_target_or_default,
    storage_location_text,
)

MERGEABLE_MOVEMENT_REASONS = {MOVEMENT_REASON_ARRIVAL, MOVEMENT_REASON_MOVE}


def sample_object_id(sample: Any) -> str:
    source = sample["code"] or str(sample["id"])
    return str(source)


def row_location_snapshot(conn: Any, row: Any) -> str:
    node_id = storage_target_or_default(row["storage_node_id"], row["status"] if "status" in row.keys() else None)
    return storage_location_text(conn, int(node_id), str(row["grid_cell"] or "").strip() or None)


def record_reagent_transfer(
    conn: Any,
    *,
    item_id: int,
    object_id: str,
    from_node_id: int,
    from_position: str | None,
    to_node_id: int,
    to_position: str | None,
    user_id: int | None,
    reason: str,
    note: str = "",
    moved_at: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO movements
            (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
             to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
             moved_by, moved_at, reason, note)
        VALUES ('试剂', ?, 'reagent', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            object_id,
            item_id,
            from_node_id,
            from_position,
            to_node_id,
            to_position,
            storage_location_text(conn, from_node_id, from_position),
            storage_location_text(conn, to_node_id, to_position),
            user_id,
            moved_at or now_text(),
            reason,
            note,
        ),
    )
    return int(cur.lastrowid)


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
        and reason in {MOVEMENT_REASON_MOVE, MOVEMENT_REASON_SPACE_MOVE}
    )
    return item


def same_storage_position(row: Any, node_id: Any, position: Any) -> bool:
    return int(row["storage_node_id"] or SYSTEM_UNPLACED_NODE_ID) == int(node_id or SYSTEM_UNPLACED_NODE_ID) and str(row["grid_cell"] or "").strip() == str(position or "").strip()


def same_movement_position(from_node_id: Any, from_position: Any, to_node_id: Any, to_position: Any) -> bool:
    return (
        int(from_node_id or SYSTEM_UNPLACED_NODE_ID) == int(to_node_id or SYSTEM_UNPLACED_NODE_ID)
        and str(from_position or "").strip() == str(to_position or "").strip()
    )


def _movement_note(data: dict[str, Any]) -> str:
    note = str(data.get("note", "")).strip()
    detail = str(data.get("reason", "")).strip()
    return note or detail


def movement_merge_window_minutes() -> int:
    value = load_dropdown_options().get("movement_merge_window_minutes", 30)
    try:
        return max(0, min(int(value), 24 * 60))
    except (TypeError, ValueError):
        return 30


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _merge_note(old_note: Any, new_note: str) -> str:
    old_text = str(old_note or "").strip()
    new_text = str(new_note or "").strip()
    return new_text or old_text


def find_mergeable_movement(conn: Any, item_type: str, item_id: int, timestamp: str) -> Any | None:
    window = movement_merge_window_minutes()
    if window <= 0:
        return None
    rows = conn.execute(
        """
        SELECT *
        FROM movements
        WHERE item_type = ? AND item_id = ? AND reverted_by_movement_id IS NULL
        ORDER BY moved_at DESC, id DESC
        LIMIT 5
        """,
        (item_type, item_id),
    ).fetchall()
    current_time = _parse_time(timestamp)
    if current_time is None:
        return None
    for row in rows:
        reason = str(row["reason"] or "")
        if reason not in MERGEABLE_MOVEMENT_REASONS:
            return None
        moved_time = _parse_time(row["moved_at"])
        if moved_time is None:
            return None
        elapsed = current_time - moved_time
        if timedelta(0) <= elapsed <= timedelta(minutes=window):
            return row
        return None
    return None


def merge_movement_record(
    conn: Any,
    row: Any,
    *,
    object_type: str,
    object_id: str,
    to_node_id: int,
    to_position: str | None,
    to_location: str,
    user_id: int,
    moved_at: str,
    note: str,
) -> Any:
    conn.execute(
        """
        UPDATE movements
        SET object_type = ?, object_id = ?,
            to_storage_node_id = ?, to_grid_cell = ?, to_location_snapshot = ?,
            moved_by = ?, moved_at = ?, note = ?
        WHERE id = ?
        """,
        (
            object_type,
            object_id,
            to_node_id,
            to_position,
            to_location,
            user_id,
            moved_at,
            _merge_note(row["note"], note),
            row["id"],
        ),
    )
    return conn.execute("SELECT * FROM movements WHERE id = ?", (row["id"],)).fetchone()


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


def _is_rollback_deletable_movement(row: Any) -> bool:
    reason = str(row["reason"] or "")
    if reason not in {MOVEMENT_REASON_MOVE, MOVEMENT_REASON_SPACE_MOVE}:
        return False
    if row["reverted_by_movement_id"] is not None:
        return False
    object_type = str(row["object_type"] or "")
    if object_type not in {"试剂", "临床标本", "空间"}:
        return False
    if object_type == "临床标本" and not row["item_id"]:
        return False
    return True


def _has_later_movement_for_object(conn: Any, row: Any) -> bool:
    moved_at = str(row["moved_at"] or "")
    movement_id = int(row["id"])
    params: list[Any]
    if row["item_type"] and row["item_id"] is not None:
        where = "item_type = ? AND item_id = ?"
        params = [row["item_type"], row["item_id"]]
    else:
        where = "object_type = ? AND object_id = ?"
        params = [row["object_type"], row["object_id"]]
    later = conn.execute(
        f"""
        SELECT 1
        FROM movements
        WHERE {where}
          AND (moved_at > ? OR (moved_at = ? AND id > ?))
        LIMIT 1
        """,
        [*params, moved_at, moved_at, movement_id],
    ).fetchone()
    return later is not None


def list_movements() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.*, m.from_location_snapshot AS from_location, m.to_location_snapshot AS to_location,
                   u.display_name AS moved_by_name
            FROM movements m LEFT JOIN users u ON u.id = m.moved_by
            ORDER BY m.moved_at DESC LIMIT 200
            """
        ).fetchall()
        items = []
        for row in rows:
            item = movement_item(row)
            if item["can_rollback"] and _has_later_movement_for_object(conn, row):
                item["can_rollback"] = False
            items.append(item)
    return {"items": items, "count": len(items)}


def create_movement(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    item_type = str(data.get("item_type", "reagent")).strip() or "reagent"
    item_id = clean_optional_positive_int(data.get("item_id")) or 0
    if item_type not in {"reagent", "sample"}:
        raise ApiError(400, "移动类型不正确")
    if not item_id:
        raise ApiError(400, "必须选择库存")
    to_node_id = storage_target_or_default(data.get("to_storage_node_id"))
    if to_node_id <= 0 and to_node_id != SYSTEM_UNPLACED_NODE_ID:
        raise ApiError(400, "移动目标只能是真实空间或未归位")
    position = str(data.get("grid_cell", "")).strip() or None
    timestamp = now_text()
    with connect() as conn:
        position = position if to_node_id > 0 else None
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
                "reason": MOVEMENT_REASON_MOVE,
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
        note = _movement_note(data)
        merge_target = find_mergeable_movement(conn, item_type, item_id, timestamp)
        if merge_target is not None:
            row = merge_movement_record(
                conn,
                merge_target,
                object_type=object_type,
                object_id=object_id,
                to_node_id=to_node_id,
                to_position=position,
                to_location=to_location,
                user_id=user["id"],
                moved_at=timestamp,
                note=note,
            )
            old_row = row_dict(merge_target)
            if same_movement_position(row["from_storage_node_id"], row["from_grid_cell"], row["to_storage_node_id"], row["to_grid_cell"]):
                conn.execute(
                    "UPDATE movements SET reverted_by_movement_id = NULL WHERE reverted_by_movement_id = ?",
                    (row["id"],),
                )
                conn.execute("DELETE FROM movements WHERE id = ?", (row["id"],))
                create_audit(conn, user["id"], "api_delete_merged_movement", "movements", row["id"], data, old_row)
                conn.commit()
                item_result = movement_item(row)
                item_result["merged"] = True
                item_result["unchanged"] = True
                item_result["deleted"] = True
                item_result["can_rollback"] = False
                return {"item": item_result}
            create_audit(conn, user["id"], "api_merge_movement", "movements", row["id"], data, old_row)
            conn.commit()
            item_result = movement_item(row)
            item_result["merged"] = True
            return {"item": item_result}
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
                MOVEMENT_REASON_MOVE, note,
            ),
        )
        create_audit(conn, user["id"], "api_create_movement", "movements", cur.lastrowid, data)
        conn.commit()
        row = conn.execute("SELECT * FROM movements WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": movement_item(row)}


def rollback_movement(movement_id: int, user: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        movement = conn.execute("SELECT * FROM movements WHERE id = ?", (movement_id,)).fetchone()
        if movement is None:
            raise ApiError(404, "移动记录不存在")
        if not _is_rollback_deletable_movement(movement):
            raise ApiError(409, "只有位置移动和空间移动记录可以回滚")
        if _has_later_movement_for_object(conn, movement):
            raise ApiError(409, "该对象在这条记录之后还有移动记录，不能回滚")
        conn.execute("DELETE FROM movements WHERE id = ?", (movement_id,))
        create_audit(conn, user["id"], "api_delete_movement_record", "movements", movement_id, {"reason": "rollback_delete"}, row_dict(movement))
        conn.commit()
    return {"ok": True, "deleted_id": movement_id, "item": row_dict(movement)}


def list_checkouts() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.*, m.from_location_snapshot AS from_location, m.to_location_snapshot AS to_location,
                   u.display_name AS moved_by_name
            FROM movements m LEFT JOIN users u ON u.id = m.moved_by
            WHERE m.reason = ? OR m.to_storage_node_id = ?
            ORDER BY m.moved_at DESC LIMIT 200
            """,
            (MOVEMENT_REASON_CHECKOUT, SYSTEM_CHECKED_OUT_NODE_ID),
        ).fetchall()
    return {"items": rows_list(rows), "count": len(rows)}


def create_checkout(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    item_type = str(data.get("item_type", "reagent")).strip() or "reagent"
    item_id = clean_optional_positive_int(data.get("item_id")) or 0
    if item_type not in {"reagent", "sample"}:
        raise ApiError(400, "出库类型不正确")
    if not item_id:
        raise ApiError(400, "必须选择出库库存")
    note = _movement_note(data)
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
            assign_sample_to_node(conn, item_id, SYSTEM_CHECKED_OUT_NODE_ID, user["id"])
        else:
            conn.execute(
                """
                UPDATE reagents
                SET status = ?, quantity = 0, updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (STATUS_CONSUMED, user["id"], timestamp, item_id),
            )
            assign_reagent_to_node(conn, item_id, SYSTEM_CHECKED_OUT_NODE_ID, user["id"])
        cur = conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
                 to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
                 moved_by, moved_at, reason, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_type, object_id, item_type, item_id, from_node_id, from_position,
                SYSTEM_CHECKED_OUT_NODE_ID, from_location, storage_location_text(conn, SYSTEM_CHECKED_OUT_NODE_ID),
                user["id"], timestamp, MOVEMENT_REASON_CHECKOUT, note,
            ),
        )
        create_audit(conn, user["id"], "api_create_checkout", "movements", cur.lastrowid, data)
        conn.commit()
        row = conn.execute("SELECT * FROM movements WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": movement_item(row)}
