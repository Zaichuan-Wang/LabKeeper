from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from core.common import ApiError, clean_int_range, clean_optional_positive_int, create_audit, now_text, row_dict, rows_list, safe_float
from core.config import EXPIRATION_REMIND_DAYS
from core.constants import (
    PHYSICAL_INVENTORY_STATUS_SQL,
    STATUS_AVAILABLE,
    STATUS_CONSUMED,
    STATUS_DISABLED,
    VALIDATION_UNVERIFIED,
)
from db.database import connect
from services.storage_inventory import (
    assign_reagent_to_node,
    attach_aliquot_totals,
    normalize_consumed_reagent_fields,
    normalize_reagent_item,
    occupies_storage,
    reagent_should_leave_storage,
    release_reagent_storage,
    sequential_frame_positions,
)


def dashboard() -> dict[str, Any]:
    with connect() as conn:
        total_reagents = conn.execute("SELECT COUNT(*) AS n FROM reagents").fetchone()["n"]
        total_samples = conn.execute("SELECT COUNT(*) AS n FROM clinical_samples").fetchone()["n"]
        total_inventory = total_reagents + total_samples
        unplaced_reagents = conn.execute(
            f"SELECT COUNT(*) AS n FROM reagents WHERE storage_node_id IS NULL AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}",
        ).fetchone()["n"]
        unplaced_samples = conn.execute(
            f"SELECT COUNT(*) AS n FROM clinical_samples WHERE storage_node_id IS NULL AND status IN {PHYSICAL_INVENTORY_STATUS_SQL}",
        ).fetchone()["n"]
        pending_orders = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM orders o
            WHERE COALESCE(o.status, '') != ?
              AND NOT EXISTS (SELECT 1 FROM arrivals a WHERE a.order_id = o.id)
            """,
            (STATUS_DISABLED,),
        ).fetchone()["n"]
        todo_validations = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM reagents
            WHERE validation_status IN (?, '待复核')
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            """,
            (VALIDATION_UNVERIFIED,),
        ).fetchone()["n"]
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
        ).fetchone()["n"]
        upcoming_count = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM reagents
            WHERE expiration_date IS NOT NULL AND expiration_date != ''
              AND expiration_date >= ? AND expiration_date <= ?
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            """,
            (today, until),
        ).fetchone()["n"]
        storage_stats = conn.execute(
            """
            SELECT
              COUNT(*) AS storage_nodes,
              SUM(CASE WHEN COALESCE(rows, 1) = 1 AND COALESCE(cols, 1) = 1 THEN 1 ELSE 0 END) AS unframed_spaces,
              SUM(CASE WHEN NOT (COALESCE(rows, 1) = 1 AND COALESCE(cols, 1) = 1) THEN 1 ELSE 0 END) AS framed_spaces
            FROM storage_nodes
            """
        ).fetchone()
        category_rows = conn.execute(
            "SELECT COALESCE(category, '未分类') AS category, COUNT(*) AS n FROM reagents GROUP BY category ORDER BY n DESC LIMIT 8"
        ).fetchall()
        status_rows = conn.execute(
            """
            SELECT '试剂：' || COALESCE(status, '未知') AS status, COUNT(*) AS n
            FROM reagents GROUP BY status
            UNION ALL
            SELECT '标本：' || COALESCE(status, '未知') AS status, COUNT(*) AS n
            FROM clinical_samples GROUP BY status
            ORDER BY n DESC
            """
        ).fetchall()
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
            SELECT a.*, a.location_snapshot AS storage_location, u.display_name AS received_by_name
            FROM arrivals a LEFT JOIN users u ON u.id = a.received_by
            WHERE a.item_type = 'reagent' AND a.item_id = ?
            ORDER BY a.created_at DESC
            """,
            (reagent_id,),
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


def insert_reagent_row(
    conn: Any,
    values: dict[str, Any],
    user_id: int,
    node_id: int | None = None,
    position: str | None = None,
) -> dict[str, Any]:
    cols = list(values.keys())
    cur = conn.execute(
        f"INSERT INTO reagents ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
        [values[col] for col in cols],
    )
    reagent_id = int(cur.lastrowid)
    if not values["code"]:
        conn.execute("UPDATE reagents SET code = ? WHERE id = ?", (f"RG{reagent_id:06d}", reagent_id))
    if node_id and not reagent_should_leave_storage(values["status"], values["quantity"]):
        assign_reagent_to_node(conn, reagent_id, node_id, user_id, position)
    row = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
    return normalize_reagent_item(row, conn)


def create_reagent(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "其他")).strip() or "其他"
    if not name:
        raise ApiError(400, "试剂名称不能为空")
    timestamp = now_text()
    values = {
        "code": str(data.get("code", "")).strip() or None,
        "source_code": str(data.get("source_code", "")).strip() or None,
        "aliquot_no": None,
        "name": name,
        "category": category,
        "brand": str(data.get("brand", "")).strip(),
        "catalog_no": str(data.get("catalog_no", "")).strip(),
        "amount": None if data.get("amount") in (None, "") else safe_float(data.get("amount"), 0),
        "amount_unit": str(data.get("amount_unit", "")).strip(),
        "quantity": safe_float(data.get("quantity"), 0),
        "status": str(data.get("status", STATUS_AVAILABLE)).strip() or STATUS_AVAILABLE,
        "storage_node_id": None,
        "position_in_box": str(data.get("position_in_box", "")).strip(),
        "entry_date": str(data.get("entry_date", "")).strip(),
        "expiration_date": str(data.get("expiration_date", "")).strip(),
        "validation_status": str(data.get("validation_status", VALIDATION_UNVERIFIED)).strip() or VALIDATION_UNVERIFIED,
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
    start_position = str(data.get("position_in_box", "")).strip() or None
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
                items.append(item)
        else:
            values["aliquot_no"] = None
            items = [insert_reagent_row(conn, values, user["id"], node_id, start_position)]
        create_audit(conn, user["id"], "api_create_reagent", "reagents", items[0]["id"], data)
        conn.commit()
        item_ids = [item["id"] for item in items]
        placeholders = ",".join("?" for _ in item_ids)
        rows = conn.execute(f"SELECT * FROM reagents WHERE id IN ({placeholders}) ORDER BY id", item_ids).fetchall()
        items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in rows])
    return {"item": items[0], "items": items, "count": len(items)}


def update_reagent(reagent_id: int, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "code", "source_code", "name", "category", "brand", "catalog_no", "amount", "amount_unit", "quantity", "status",
        "storage_node_id", "position_in_box", "entry_date", "expiration_date", "validation_status", "note",
    ]
    move_node_requested = "storage_node_id" in data
    move_node_id = data.get("storage_node_id") if move_node_requested else None
    move_position = data.get("position_in_box", "")
    updates = {key: data[key] for key in allowed if key in data and key not in {"storage_node_id", "position_in_box"}}
    if not updates and not move_node_requested:
        raise ApiError(400, "没有可更新字段")
    if "quantity" in updates:
        updates["quantity"] = safe_float(updates["quantity"], 0)
    if "code" in updates:
        updates["code"] = str(updates["code"] or "").strip()
        if not updates["code"]:
            raise ApiError(400, "编号不能为空")
    if "source_code" in updates:
        updates["source_code"] = str(updates["source_code"] or "").strip() or None
    if "amount" in updates:
        updates["amount"] = None if updates["amount"] in (None, "") else safe_float(updates["amount"], 0)
    if "amount_unit" in updates:
        updates["amount_unit"] = str(updates["amount_unit"] or "").strip()
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
        current = conn.execute("SELECT status, quantity FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
        leave_storage = reagent_should_leave_storage(current["status"], current["quantity"]) if current else False
        if leave_storage:
            release_reagent_storage(conn, reagent_id, user["id"])
        elif move_node_requested:
            target_node_id = clean_optional_positive_int(move_node_id)
            assign_reagent_to_node(conn, reagent_id, target_node_id, user["id"], str(move_position or "").strip() or None)
        create_audit(conn, user["id"], "api_update_reagent", "reagents", reagent_id, data, row_dict(old))
        conn.commit()
        row = conn.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
        items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn)])
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
        raise ApiError(400, "必须选择要分装的试剂/耗材")
    aliquot_count = clean_int_range(data.get("tube_count"), 1, 1, 300)
    node_id = clean_optional_positive_int(data.get("storage_node_id"))
    start_position = str(data.get("position_in_box", "")).strip() or None
    timestamp = now_text()
    with connect() as conn:
        source = conn.execute("SELECT * FROM reagents WHERE id = ?", (source_id,)).fetchone()
        if source is None:
            raise ApiError(404, "试剂/耗材不存在")
        if not occupies_storage(source["status"]) or reagent_should_leave_storage(source["status"], source["quantity"]):
            raise ApiError(409, "只有已入库的试剂/耗材可以分装")
        source_code = str(source["source_code"] or source["code"] or source["id"])
        first_aliquot = _next_reagent_aliquot_no(conn, source_code)
        positions = sequential_frame_positions(conn, node_id, aliquot_count, start_position) if node_id else [None] * aliquot_count
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
                "status": source["status"] or STATUS_AVAILABLE,
                "storage_node_id": None,
                "position_in_box": None,
                "entry_date": source["entry_date"] or date.today().isoformat(),
                "expiration_date": source["expiration_date"] or "",
                "validation_status": source["validation_status"] or VALIDATION_UNVERIFIED,
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
            conn.execute("UPDATE reagents SET code = ? WHERE id = ?", (f"RG{reagent_id:06d}", reagent_id))
            if node_id:
                assign_reagent_to_node(conn, reagent_id, node_id, user["id"], positions[offset])
        create_audit(conn, user["id"], "api_create_reagent_aliquots", "reagents", inserted_ids[0], data, row_dict(source))
        conn.commit()
        placeholders = ",".join("?" for _ in inserted_ids)
        rows = conn.execute(f"SELECT * FROM reagents WHERE id IN ({placeholders}) ORDER BY id", inserted_ids).fetchall()
        items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in rows])
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
            SELECT id, code, name, category, quantity, storage_node_id, position_in_box, expiration_date, status
            FROM reagents
            WHERE expiration_date IS NOT NULL AND expiration_date != '' AND expiration_date < ?
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            ORDER BY expiration_date ASC LIMIT 100
            """,
            (today,),
        ).fetchall()
        upcoming = conn.execute(
            f"""
            SELECT id, code, name, category, quantity, storage_node_id, position_in_box, expiration_date, status
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
            SELECT o.*, u.display_name AS requester_name,
                   0 AS arrival_count,
                   '未到货' AS arrival_status
            FROM orders o LEFT JOIN users u ON u.id = o.requester_id
            WHERE COALESCE(o.status, '') != ?
              AND NOT EXISTS (SELECT 1 FROM arrivals a WHERE a.order_id = o.id)
            ORDER BY o.updated_at DESC LIMIT 500
            """,
            (STATUS_DISABLED,),
        ).fetchall()
        unvalidated_antibodies = conn.execute(
            f"""
            SELECT id, code, name, category, brand, catalog_no, quantity,
                   storage_node_id, position_in_box, expiration_date, status, validation_status, updated_at
            FROM reagents
            WHERE (category LIKE '%抗体%' OR name LIKE '%抗体%' OR name LIKE '%antibody%' OR name LIKE '%Anti-%')
              AND COALESCE(validation_status, '') IN (?, '待复核')
              AND COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}
            ORDER BY updated_at DESC LIMIT 500
            """,
            (VALIDATION_UNVERIFIED,),
        ).fetchall()
    return {
        "overdue": attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in overdue]),
        "upcoming": attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in upcoming]),
        "pending_orders": rows_list(pending_orders),
        "unvalidated_antibodies": attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in unvalidated_antibodies]),
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
