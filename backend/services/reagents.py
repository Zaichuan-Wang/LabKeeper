from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from core.common import ApiError, clean_int_range, clean_optional_positive_int, create_audit, now_text, row_dict, rows_list, safe_float
from core.config import EXPIRATION_REMIND_DAYS
from core.constants import (
    MOVEMENT_REASON_ARRIVAL,
    MOVEMENT_REASON_ORDER,
    MOVEMENT_REASON_REGISTER,
    MOVEMENT_REASON_MOVE,
    MOVEMENT_REASON_STATUS,
    PHYSICAL_INVENTORY_STATUS_SQL,
    STATUS_AVAILABLE,
    STATUS_CONSUMED,
    STATUS_DISABLED,
    STATUS_ORDERED,
    SYSTEM_CHECKED_OUT_NODE_ID,
    SYSTEM_NOT_ARRIVED_NODE_ID,
    SYSTEM_NOT_ORDERED_NODE_ID,
    SYSTEM_UNPLACED_NODE_ID,
)
from db.database import connect
from services.movements import record_reagent_transfer
from services.storage_inventory import (
    assign_reagent_to_node,
    attach_aliquot_totals,
    attach_reagent_validation_statuses,
    normalize_consumed_reagent_fields,
    normalize_reagent_item,
    occupies_storage,
    reagent_validation_status_sql,
    reagent_should_leave_storage,
    release_reagent_storage,
    sequential_frame_positions,
    storage_location_text,
    storage_target_or_default,
)


def dashboard(visible_types: set[str] | None = None) -> dict[str, Any]:
    visible = {"reagent", "sample"} if visible_types is None else visible_types
    with connect() as conn:
        total_reagents = conn.execute("SELECT COUNT(*) AS n FROM reagents").fetchone()["n"] if "reagent" in visible else 0
        total_samples = conn.execute("SELECT COUNT(*) AS n FROM clinical_samples").fetchone()["n"] if "sample" in visible else 0
        total_inventory = total_reagents + total_samples
        unplaced_reagents = conn.execute(
            f"SELECT COUNT(*) AS n FROM reagents WHERE storage_node_id = ? AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}",
            (SYSTEM_UNPLACED_NODE_ID,),
        ).fetchone()["n"] if "reagent" in visible else 0
        unplaced_samples = conn.execute(
            f"SELECT COUNT(*) AS n FROM clinical_samples WHERE storage_node_id = ? AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}",
            (SYSTEM_UNPLACED_NODE_ID,),
        ).fetchone()["n"] if "sample" in visible else 0
        pending_orders = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM reagents
            WHERE status = ? AND storage_node_id = ?
            """,
            (STATUS_ORDERED, SYSTEM_NOT_ARRIVED_NODE_ID),
        ).fetchone()["n"] if "reagent" in visible else 0
        todo_validations = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM reagents
            WHERE {reagent_validation_status_sql('reagents')} IN ('未验证', '待复核')
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            """
        ).fetchone()["n"] if "reagent" in visible else 0
        today = date.today().isoformat()
        until = (date.today() + timedelta(days=EXPIRATION_REMIND_DAYS)).isoformat()
        overdue_count = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM reagents
            WHERE expiration_date IS NOT NULL AND expiration_date != ''
              AND expiration_date < ?
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            """,
            (today,),
        ).fetchone()["n"] if "reagent" in visible else 0
        upcoming_count = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM reagents
            WHERE expiration_date IS NOT NULL AND expiration_date != ''
              AND expiration_date >= ? AND expiration_date <= ?
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            """,
            (today, until),
        ).fetchone()["n"] if "reagent" in visible else 0
        storage_stats = conn.execute(
            """
            SELECT
              COUNT(*) AS storage_nodes,
              SUM(CASE WHEN COALESCE(rows, 1) = 1 AND COALESCE(cols, 1) = 1 THEN 1 ELSE 0 END) AS unframed_spaces,
              SUM(CASE WHEN NOT (COALESCE(rows, 1) = 1 AND COALESCE(cols, 1) = 1) THEN 1 ELSE 0 END) AS framed_spaces
            FROM storage_nodes
            WHERE id > 0 AND COALESCE(node_type, 'space') != 'system'
            """
        ).fetchone()
        category_rows = conn.execute(
            "SELECT COALESCE(category, '未分类') AS category, COUNT(*) AS n FROM reagents GROUP BY category ORDER BY n DESC LIMIT 8"
        ).fetchall() if "reagent" in visible else []
        status_queries = []
        if "reagent" in visible:
            status_queries.append("SELECT '试剂：' || COALESCE(status, '未知') AS status, COUNT(*) AS n FROM reagents GROUP BY status")
        if "sample" in visible:
            status_queries.append("SELECT '标本：' || COALESCE(status, '未知') AS status, COUNT(*) AS n FROM clinical_samples GROUP BY status")
        status_rows = conn.execute(" UNION ALL ".join(status_queries) + " ORDER BY n DESC").fetchall() if status_queries else []
    return {
        "metrics": {
            "total_reagents": total_reagents,
            "total_samples": total_samples,
            "total_inventory": total_inventory,
            "unplaced_inventory": unplaced_reagents + unplaced_samples,
            "pending_orders": pending_orders,
            "todo_validations": todo_validations,
            "overdue": overdue_count,
            "upcoming": upcoming_count,
            "remind_days": EXPIRATION_REMIND_DAYS,
            "storage_nodes": int(storage_stats["storage_nodes"] or 0),
            "unframed_spaces": int(storage_stats["unframed_spaces"] or 0),
            "framed_spaces": int(storage_stats["framed_spaces"] or 0),
        },
        "category_breakdown": rows_list(category_rows),
        "status_breakdown": rows_list(status_rows),
    }


def reagent_detail(reagent_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
        if row is None:
            raise ApiError(404, "试剂不存在")
        catalog_no = str(row["catalog_no"] or "").strip()
        validations = conn.execute(
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
        arrivals = conn.execute(
            """
            SELECT m.id, m.item_id, m.moved_at AS created_at, m.moved_at,
                   m.to_storage_node_id AS storage_node_id, m.to_grid_cell AS grid_cell,
                   m.to_location_snapshot AS location_snapshot, m.to_location_snapshot AS storage_location,
                   m.note, r.entry_date, r.expiration_date, u.display_name AS received_by_name,
                   m.moved_by AS received_by
            FROM movements m
            JOIN reagents r ON r.id = m.item_id AND m.item_type = 'reagent'
            LEFT JOIN users u ON u.id = m.moved_by
            WHERE m.item_type = 'reagent' AND m.item_id = ? AND m.reason = ?
            ORDER BY m.moved_at DESC, m.id DESC
            """,
            (reagent_id, MOVEMENT_REASON_ARRIVAL),
        ).fetchall()
        movements = conn.execute(
            """
            SELECT m.*, m.from_location_snapshot AS from_location, m.to_location_snapshot AS to_location,
                   u.display_name AS moved_by_name
            FROM movements m LEFT JOIN users u ON u.id = m.moved_by
            WHERE m.item_type = 'reagent' AND m.item_id = ?
            ORDER BY m.moved_at DESC
            """,
            (reagent_id,),
        ).fetchall()
        items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn)])
        attach_reagent_validation_statuses(conn, items)
    return {"item": items[0], "validations": rows_list(validations), "arrivals": rows_list(arrivals), "movements": rows_list(movements)}


def split_count_from_quantity(quantity: Any) -> int:
    try:
        number = float(quantity)
    except (TypeError, ValueError):
        return 1
    if number <= 1:
        return 1
    if not number.is_integer():
        raise ApiError(400, "分别登记时，数量必须是整数")
    return min(int(number), 300)


def reagent_target_for_status(status: str | None, requested_node_id: Any = None) -> int:
    clean_status = str(status or "").strip()
    if clean_status == STATUS_ORDERED:
        return SYSTEM_NOT_ARRIVED_NODE_ID
    if clean_status == STATUS_CONSUMED:
        return SYSTEM_CHECKED_OUT_NODE_ID
    return storage_target_or_default(requested_node_id, clean_status)


def create_reagent_movement(
    conn: Any,
    item: dict[str, Any],
    *,
    from_node_id: int,
    reason: str,
    user_id: int | None,
    note: str = "",
) -> None:
    to_node_id = int(item.get("storage_node_id") or SYSTEM_UNPLACED_NODE_ID)
    to_position = str(item.get("grid_cell") or "").strip() or None
    record_reagent_transfer(
        conn,
        item_id=int(item["id"]),
        object_id=str(item.get("code") or item.get("id")),
        from_node_id=from_node_id,
        from_position=None,
        to_node_id=to_node_id,
        to_position=to_position,
        user_id=user_id,
        reason=reason,
        note=note,
    )


def insert_reagent_row(
    conn: Any,
    values: dict[str, Any],
    user_id: int,
    node_id: int | None = None,
    position: str | None = None,
) -> dict[str, Any]:
    target_node_id = reagent_target_for_status(values.get("status"), node_id if node_id is not None else values.get("storage_node_id"))
    values["storage_node_id"] = target_node_id
    if target_node_id <= 0:
        values["grid_cell"] = None
    cols = list(values.keys())
    cur = conn.execute(
        f"INSERT INTO reagents ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
        [values[col] for col in cols],
    )
    reagent_id = int(cur.lastrowid)
    if not values["code"]:
        conn.execute("UPDATE reagents SET code = ? WHERE id = ?", (f"RG{reagent_id:06d}", reagent_id))
    assign_reagent_to_node(conn, reagent_id, target_node_id, user_id, position)
    row = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
    return normalize_reagent_item(row, conn)


def create_reagent(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "其他")).strip() or "其他"
    if not name:
        raise ApiError(400, "试剂名称不能为空")
    timestamp = now_text()
    values = {
        "code": None,
        "source_code": str(data.get("source_code", "")).strip() or None,
        "aliquot_no": None,
        "name": name,
        "category": category,
        "brand": str(data.get("brand", "")).strip(),
        "catalog_no": str(data.get("catalog_no", "")).strip(),
        "amount": None if data.get("amount") in (None, "") else safe_float(data.get("amount"), 0),
        "amount_unit": str(data.get("amount_unit", "")).strip(),
        "quantity": safe_float(data.get("quantity"), 0),
        "price": None if data.get("price") in (None, "") else safe_float(data.get("price"), 0),
        "status": str(data.get("status", STATUS_AVAILABLE)).strip() or STATUS_AVAILABLE,
        "storage_node_id": None,
        "grid_cell": str(data.get("grid_cell", "")).strip(),
        "entry_date": str(data.get("entry_date", "")).strip(),
        "expiration_date": str(data.get("expiration_date", "")).strip(),
        "note": str(data.get("note", "")).strip(),
        "created_by": user["id"],
        "updated_by": user["id"],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    normalize_consumed_reagent_fields(values)
    separate_items = bool(data.get("separate_items", True))
    item_count = split_count_from_quantity(values["quantity"]) if separate_items else 1
    node_id = clean_optional_positive_int(data.get("storage_node_id"))
    start_position = str(data.get("grid_cell", "")).strip() or None
    movement_reason = MOVEMENT_REASON_ORDER if values["status"] == STATUS_ORDERED else MOVEMENT_REASON_REGISTER
    with connect() as conn:
        if separate_items and item_count > 1:
            positions = sequential_frame_positions(conn, node_id, item_count, start_position) if node_id else [None] * item_count
            items = []
            source_code = str(values.get("source_code") or "").strip() or None
            for index in range(item_count):
                row_values = values.copy()
                row_values["code"] = None
                row_values["quantity"] = 1
                row_values["aliquot_no"] = index + 1
                row_values["source_code"] = source_code
                item = insert_reagent_row(conn, row_values, user["id"], node_id, positions[index])
                if source_code is None:
                    source_code = item["code"]
                    conn.execute("UPDATE reagents SET source_code = ? WHERE id = ?", (source_code, item["id"]))
                    item["source_code"] = source_code
                create_reagent_movement(conn, item, from_node_id=SYSTEM_NOT_ORDERED_NODE_ID, reason=movement_reason, user_id=user["id"], note=values["note"])
                items.append(item)
        else:
            values["aliquot_no"] = None
            items = [insert_reagent_row(conn, values, user["id"], node_id, start_position)]
            create_reagent_movement(conn, items[0], from_node_id=SYSTEM_NOT_ORDERED_NODE_ID, reason=movement_reason, user_id=user["id"], note=values["note"])
        create_audit(conn, user["id"], "api_create_reagent", "reagents", items[0]["id"], data)
        conn.commit()
        item_ids = [item["id"] for item in items]
        placeholders = ",".join("?" for _ in item_ids)
        rows = conn.execute(f"SELECT * FROM reagents WHERE id IN ({placeholders}) ORDER BY id", item_ids).fetchall()
        items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in rows])
        attach_reagent_validation_statuses(conn, items)
    return {"item": items[0], "items": items, "count": len(items)}


def update_reagent(reagent_id: int, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "source_code", "name", "category", "brand", "catalog_no", "amount", "amount_unit", "quantity", "status",
        "price", "storage_node_id", "grid_cell", "entry_date", "expiration_date", "note",
    ]
    move_node_requested = "storage_node_id" in data
    move_node_id = data.get("storage_node_id") if move_node_requested else None
    move_position = data.get("grid_cell", "")
    updates = {key: data[key] for key in allowed if key in data and key not in {"storage_node_id", "grid_cell"}}
    if not updates and not move_node_requested:
        raise ApiError(400, "没有可更新字段")
    if "quantity" in updates:
        updates["quantity"] = safe_float(updates["quantity"], 0)
    if "source_code" in updates:
        updates["source_code"] = str(updates["source_code"] or "").strip() or None
    if "amount" in updates:
        updates["amount"] = None if updates["amount"] in (None, "") else safe_float(updates["amount"], 0)
    if "amount_unit" in updates:
        updates["amount_unit"] = str(updates["amount_unit"] or "").strip()
    if "price" in updates:
        updates["price"] = None if updates["price"] in (None, "") else safe_float(updates["price"], 0)
    updates["updated_by"] = user["id"]
    updates["updated_at"] = now_text()
    with connect() as conn:
        old = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
        if old is None:
            raise ApiError(404, "试剂不存在")
        status_for_rule = updates.get("status", old["status"])
        quantity_for_rule = updates.get("quantity", old["quantity"])
        normalize_patch = {"status": status_for_rule, "quantity": quantity_for_rule}
        normalize_consumed_reagent_fields(normalize_patch)
        if normalize_patch["status"] == STATUS_CONSUMED:
            updates["status"] = STATUS_CONSUMED
            updates["quantity"] = 0
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(f"UPDATE reagents SET {assignments} WHERE id = ?", list(updates.values()) + [reagent_id])
        current = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
        leave_storage = reagent_should_leave_storage(current["status"], current["quantity"]) if current else False
        if leave_storage:
            release_reagent_storage(conn, reagent_id, user["id"])
        else:
            current_node_id = int(current["storage_node_id"] or SYSTEM_UNPLACED_NODE_ID)
            needs_default_from_system = current_node_id <= 0 and current_node_id != SYSTEM_UNPLACED_NODE_ID
            if move_node_requested or needs_default_from_system:
                target_node_id = storage_target_or_default(move_node_id if move_node_requested else None, current["status"])
                if target_node_id <= 0 and target_node_id != SYSTEM_UNPLACED_NODE_ID:
                    raise ApiError(400, "存放位置只能选择真实空间或未归位")
                target_position = str(move_position or "").strip() or None
                target_position = target_position if target_node_id > 0 else None
                from_node_id = current_node_id
                from_position = str(current["grid_cell"] or "").strip() or None
                assign_reagent_to_node(conn, reagent_id, target_node_id, user["id"], target_position)
                if int(from_node_id) != int(target_node_id) or str(from_position or "") != str(target_position or ""):
                    record_reagent_transfer(
                        conn,
                        item_id=reagent_id,
                        object_id=current["code"] or str(reagent_id),
                        from_node_id=from_node_id,
                        from_position=from_position,
                        to_node_id=target_node_id,
                        to_position=target_position,
                        user_id=user["id"],
                        reason=MOVEMENT_REASON_MOVE if move_node_requested else MOVEMENT_REASON_STATUS,
                        note="试剂位置已更新" if move_node_requested else "试剂状态调整后自动进入未归位",
                    )
        create_audit(conn, user["id"], "api_update_reagent", "reagents", reagent_id, data, row_dict(old))
        conn.commit()
        row = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
        items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn)])
        attach_reagent_validation_statuses(conn, items)
    return {"item": items[0]}


def _next_reagent_aliquot_no(conn: Any, source_code: str) -> int:
    row = conn.execute(
        """
        SELECT MAX(aliquot_no) AS n
        FROM reagents
        WHERE COALESCE(source_code, code, id) = ?
        """,
        (source_code,),
    ).fetchone()
    return int(row["n"] or 0) + 1


def create_reagent_aliquots(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    source_id = clean_optional_positive_int(data.get("source_item_id")) or 0
    if not source_id:
        raise ApiError(400, "必须选择要分装的试剂")
    aliquot_count = clean_int_range(data.get("tube_count"), 1, 1, 300)
    node_id = clean_optional_positive_int(data.get("storage_node_id"))
    start_position = str(data.get("grid_cell", "")).strip() or None
    timestamp = now_text()
    with connect() as conn:
        source = conn.execute("SELECT * FROM reagents WHERE id = ?", (source_id,)).fetchone()
        if source is None:
            raise ApiError(404, "试剂不存在")
        if not occupies_storage(source["status"]) or reagent_should_leave_storage(source["status"], source["quantity"]):
            raise ApiError(409, "只有已入库的试剂可以分装")
        source_code = str(source["source_code"] or source["code"] or source["id"])
        first_aliquot = _next_reagent_aliquot_no(conn, source_code)
        target_node_id = storage_target_or_default(node_id, STATUS_AVAILABLE)
        positions = sequential_frame_positions(conn, target_node_id, aliquot_count, start_position) if target_node_id > 0 else [None] * aliquot_count
        note = str(data.get("note", "")).strip()
        quantity = safe_float(data.get("quantity"), source["quantity"] if source["quantity"] not in (None, "") else 1)
        inserted_ids: list[int] = []
        for offset in range(aliquot_count):
            aliquot_note = f"由 {source_code} 分装" + (f"；{note}" if note else "")
            values = {
                "code": None,
                "source_code": source_code,
                "aliquot_no": first_aliquot + offset,
                "name": source["name"],
                "category": source["category"] or "其他",
                "brand": source["brand"] or "",
                "catalog_no": source["catalog_no"] or "",
                "amount": source["amount"],
                "amount_unit": source["amount_unit"] or "",
                "quantity": quantity,
                "price": source["price"],
                "status": source["status"] or STATUS_AVAILABLE,
                "storage_node_id": target_node_id,
                "grid_cell": None,
                "entry_date": source["entry_date"] or date.today().isoformat(),
                "expiration_date": source["expiration_date"] or "",
                "note": aliquot_note,
                "created_by": user["id"],
                "updated_by": user["id"],
                "created_at": timestamp,
                "updated_at": timestamp,
            }
            cols = list(values)
            cur = conn.execute(
                f"INSERT INTO reagents ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
                [values[col] for col in cols],
            )
            reagent_id = int(cur.lastrowid)
            inserted_ids.append(reagent_id)
            code = f"RG{reagent_id:06d}"
            conn.execute("UPDATE reagents SET code = ? WHERE id = ?", (code, reagent_id))
            assign_reagent_to_node(conn, reagent_id, target_node_id, user["id"], positions[offset])
            record_reagent_transfer(
                conn,
                item_id=reagent_id,
                object_id=code,
                from_node_id=int(source["storage_node_id"] or SYSTEM_UNPLACED_NODE_ID),
                from_position=str(source["grid_cell"] or "").strip() or None,
                to_node_id=target_node_id,
                to_position=positions[offset],
                user_id=user["id"],
                reason=MOVEMENT_REASON_REGISTER,
                note=aliquot_note,
            )
        create_audit(conn, user["id"], "api_create_reagent_aliquots", "reagents", inserted_ids[0], data, row_dict(source))
        conn.commit()
        placeholders = ",".join("?" for _ in inserted_ids)
        rows = conn.execute(f"SELECT * FROM reagents WHERE id IN ({placeholders}) ORDER BY id", inserted_ids).fetchall()
        items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in rows])
        attach_reagent_validation_statuses(conn, items)
    return {"item": items[0], "items": items, "count": len(items)}


def expiration(query: dict[str, list[str]] | None = None) -> dict[str, Any]:
    days = EXPIRATION_REMIND_DAYS
    if query is not None:
        days = clean_int_range(query.get("days", [str(EXPIRATION_REMIND_DAYS)])[0], EXPIRATION_REMIND_DAYS, 1, 180)
    today = date.today().isoformat()
    until = (date.today() + timedelta(days=days)).isoformat()
    with connect() as conn:
        overdue = conn.execute(
            f"""
            SELECT id, code, name, category, quantity, storage_node_id, grid_cell, expiration_date, status
            FROM reagents
            WHERE expiration_date IS NOT NULL AND expiration_date != '' AND expiration_date < ?
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            ORDER BY expiration_date ASC LIMIT 100
            """,
            (today,),
        ).fetchall()
        upcoming = conn.execute(
            f"""
            SELECT id, code, name, category, quantity, storage_node_id, grid_cell, expiration_date, status
            FROM reagents
            WHERE expiration_date IS NOT NULL AND expiration_date != ''
              AND expiration_date >= ? AND expiration_date <= ?
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            ORDER BY expiration_date ASC LIMIT 100
            """,
            (today, until),
        ).fetchall()
        pending_orders = conn.execute(
            """
            SELECT r.*, u.display_name AS requester_name,
                   0 AS arrival_count,
                   '未到货' AS arrival_status,
                   m.note AS reason,
                   m.moved_at AS ordered_at
            FROM reagents r
            JOIN movements m ON m.item_type = 'reagent' AND m.item_id = r.id AND m.reason = ?
            LEFT JOIN users u ON u.id = m.moved_by
            WHERE r.status = ? AND r.storage_node_id = ?
            ORDER BY r.updated_at DESC LIMIT 500
            """,
            (MOVEMENT_REASON_ORDER, STATUS_ORDERED, SYSTEM_NOT_ARRIVED_NODE_ID),
        ).fetchall()
        unvalidated_antibodies = conn.execute(
            f"""
            SELECT id, code, name, category, brand, catalog_no, quantity,
                   storage_node_id, grid_cell, expiration_date, status, updated_at
            FROM reagents
            WHERE (category LIKE '%抗体%' OR name LIKE '%抗体%' OR name LIKE '%antibody%' OR name LIKE '%Anti-%')
              AND {reagent_validation_status_sql('reagents')} IN ('未验证', '待复核')
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            ORDER BY updated_at DESC LIMIT 500
            """
        ).fetchall()
        overdue_items = attach_reagent_validation_statuses(conn, attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in overdue]))
        upcoming_items = attach_reagent_validation_statuses(conn, attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in upcoming]))
        unvalidated_items = attach_reagent_validation_statuses(conn, attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in unvalidated_antibodies]))
    return {
        "overdue": overdue_items,
        "upcoming": upcoming_items,
        "pending_orders": rows_list(pending_orders),
        "unvalidated_antibodies": unvalidated_items,
        "remind_days": days,
    }


def catalog_name_conflicts(catalog_no: str, name: str, exclude_reagent_id: int | None = None) -> dict[str, Any]:
    catalog = str(catalog_no or "").strip()
    clean_name = str(name or "").strip()
    if not catalog or not clean_name:
        return {"items": [], "count": 0, "has_conflict": False}
    params: list[Any] = [catalog, clean_name]
    sql = """
        SELECT id, code, name, category, brand, catalog_no, amount, amount_unit, status
        FROM reagents
        WHERE catalog_no = ? AND TRIM(COALESCE(name, '')) != ?
    """
    if exclude_reagent_id:
        sql += " AND id != ?"
        params.append(exclude_reagent_id)
    sql += " ORDER BY updated_at DESC LIMIT 20"
    with connect() as conn:
        rows = rows_list(conn.execute(sql, params).fetchall())
    return {"items": rows, "count": len(rows), "has_conflict": bool(rows)}
