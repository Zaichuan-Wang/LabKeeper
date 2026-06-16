from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from core.common import ApiError, clean_int_range, clean_optional_positive_int, create_audit, now_text, row_dict, safe_float
from core.constants import (
    MOVEMENT_REASON_MOVE,
    MOVEMENT_REASON_REGISTER,
    MOVEMENT_REASON_STATUS,
    STATUS_AVAILABLE,
    STATUS_CONSUMED,
    SYSTEM_CHECKED_OUT_NODE_ID,
    SYSTEM_UNPLACED_NODE_ID,
)
from db.database import connect
from services.options_config import dropdown_values
from services.storage_inventory import (
    assign_sample_to_node,
    attach_aliquot_totals,
    normalize_sample_item,
    occupies_storage,
    release_sample_storage,
    sequential_frame_positions,
    storage_location_text,
    storage_target_or_default,
)

SAMPLE_CODE_PREFIX = "SP"
SAMPLE_CODE_WIDTH = 6


def next_code(conn: sqlite3.Connection, prefix: str = SAMPLE_CODE_PREFIX) -> str:
    clean_prefix = (prefix or SAMPLE_CODE_PREFIX).strip() or SAMPLE_CODE_PREFIX
    rows = conn.execute(
        """
        SELECT code
        FROM clinical_samples
        WHERE code LIKE ?
        ORDER BY id DESC LIMIT 300
        """,
        (f"{clean_prefix}%",),
    ).fetchall()
    max_number = 0
    for row in rows:
        code = str(row["code"] or "")
        if not code.startswith(clean_prefix):
            continue
        suffix = code[len(clean_prefix):]
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    return f"{clean_prefix}{max_number + 1:0{SAMPLE_CODE_WIDTH}d}"


def next_aliquot_no(conn: sqlite3.Connection, code: str) -> int:
    row = conn.execute(
        "SELECT MAX(aliquot_no) AS n FROM clinical_samples WHERE COALESCE(source_code, code, id) = ?",
        (code,),
    ).fetchone()
    return int(row["n"] or 0) + 1


def ensure_unique_sample_aliquot(
    conn: sqlite3.Connection,
    code: str | None,
    aliquot_no: int | None,
    exclude_id: int | None = None,
    source_code: str | None = None,
) -> None:
    clean_code = str(code or "").strip()
    clean_source = str(source_code or clean_code).strip()
    if not clean_code:
        raise ApiError(400, "标本系统编号不能为空")
    if aliquot_no is None:
        return
    params: list[Any] = [clean_source, int(aliquot_no)]
    sql = """
        SELECT id, code, name
        FROM clinical_samples
        WHERE COALESCE(source_code, code) = ? AND aliquot_no = ?
    """
    if exclude_id:
        sql += " AND id <> ?"
        params.append(int(exclude_id))
    existing = conn.execute(sql + " LIMIT 1", params).fetchone()
    if existing is not None:
        raise ApiError(409, "该来源标本下已存在相同管号，请修改标本来源或管号。")


def normalize_sample_rows(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return attach_aliquot_totals(conn, [normalize_sample_item(row, conn) for row in rows])


def sample_target_for_status(status: str | None, requested_node_id: Any = None) -> int:
    if str(status or "").strip() == STATUS_CONSUMED:
        return SYSTEM_CHECKED_OUT_NODE_ID
    return storage_target_or_default(requested_node_id, status)


def record_sample_transfer(
    conn: sqlite3.Connection,
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
) -> None:
    conn.execute(
        """
        INSERT INTO movements
            (object_type, object_id, item_type, item_id, from_storage_node_id, from_grid_cell,
             to_storage_node_id, to_grid_cell, from_location_snapshot, to_location_snapshot,
             moved_by, moved_at, reason, note)
        VALUES ('临床标本', ?, 'sample', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            now_text(),
            reason,
            note,
        ),
    )


def sample_detail(conn: sqlite3.Connection, sample_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
    if row is None:
        raise ApiError(404, "临床标本不存在")
    items = normalize_sample_rows(conn, [row])
    return {"item": items[0]}


def get_sample(sample_id: int) -> dict[str, Any]:
    with connect() as conn:
        return sample_detail(conn, sample_id)


def insert_sample_tubes(
    conn: sqlite3.Connection,
    values: dict[str, Any],
    tube_count: int,
    user_id: int,
    node_id: int | None,
    start_position: str | None,
    auto_find_from_start: bool = False,
) -> list[dict[str, Any]]:
    target_node_id = sample_target_for_status(values.get("status"), node_id)
    values["storage_node_id"] = target_node_id
    if target_node_id <= 0:
        values["grid_cell"] = None
    if not values["source_code"]:
        values["code"] = values["code"] or next_code(conn)
        values["source_code"] = values["code"]
    first_aliquot = next_aliquot_no(conn, values["source_code"])
    if target_node_id > 0 and occupies_storage(values["status"]) and (tube_count > 1 or auto_find_from_start):
        positions = sequential_frame_positions(conn, target_node_id, tube_count, start_position)
    elif target_node_id > 0 and occupies_storage(values["status"]):
        positions = [start_position]
    else:
        positions = [None] * tube_count
    inserted: list[dict[str, Any]] = []
    for offset in range(tube_count):
        row_values = values.copy()
        if offset > 0 or not row_values["code"]:
            row_values["code"] = next_code(conn)
        row_values["aliquot_no"] = first_aliquot + offset
        ensure_unique_sample_aliquot(conn, row_values["code"], row_values["aliquot_no"], source_code=row_values["source_code"])
        cols = list(row_values.keys())
        cur = conn.execute(
            f"INSERT INTO clinical_samples ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
            [row_values[col] for col in cols],
        )
        sample_id = int(cur.lastrowid)
        assign_sample_to_node(conn, sample_id, target_node_id, user_id, positions[offset])
        row = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
        item = normalize_sample_item(row, conn)
        record_sample_transfer(
            conn,
            item_id=sample_id,
            object_id=item["code"] or str(sample_id),
            from_node_id=SYSTEM_UNPLACED_NODE_ID,
            from_position=None,
            to_node_id=int(item["storage_node_id"] or SYSTEM_UNPLACED_NODE_ID),
            to_position=str(item.get("grid_cell") or "").strip() or None,
            user_id=user_id,
            reason=MOVEMENT_REASON_REGISTER,
            note=str(row_values.get("note") or ""),
        )
        inserted.append(item)
    return attach_aliquot_totals(conn, inserted)


def insert_combined_sample(
    conn: sqlite3.Connection,
    values: dict[str, Any],
    quantity: int,
    user_id: int,
    node_id: int | None,
    start_position: str | None,
) -> list[dict[str, Any]]:
    target_node_id = sample_target_for_status(values.get("status"), node_id)
    row_values = values.copy()
    row_values["code"] = row_values["code"] or next_code(conn)
    row_values["source_code"] = row_values["source_code"] or row_values["code"]
    row_values["quantity"] = quantity
    row_values["aliquot_no"] = None
    row_values["storage_node_id"] = target_node_id
    if target_node_id <= 0:
        row_values["grid_cell"] = None
    ensure_unique_sample_aliquot(conn, row_values["code"], row_values["aliquot_no"], source_code=row_values["source_code"])
    cols = list(row_values.keys())
    cur = conn.execute(
        f"INSERT INTO clinical_samples ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
        [row_values[col] for col in cols],
    )
    sample_id = int(cur.lastrowid)
    target_position = start_position if target_node_id > 0 and occupies_storage(row_values["status"]) else None
    assign_sample_to_node(conn, sample_id, target_node_id, user_id, target_position)
    row = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
    item = normalize_sample_item(row, conn)
    record_sample_transfer(
        conn,
        item_id=sample_id,
        object_id=item["code"] or str(sample_id),
        from_node_id=SYSTEM_UNPLACED_NODE_ID,
        from_position=None,
        to_node_id=int(item["storage_node_id"] or SYSTEM_UNPLACED_NODE_ID),
        to_position=str(item.get("grid_cell") or "").strip() or None,
        user_id=user_id,
        reason=MOVEMENT_REASON_REGISTER,
        note=str(row_values.get("note") or ""),
    )
    return attach_aliquot_totals(conn, [item])


def base_sample_values(data: dict[str, Any], user: dict[str, Any], source: str | None = None) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ApiError(400, "样本号不能为空")
    code = str(data.get("code") or "").strip()
    if source:
        code = source
    source_code = str(data.get("source_code") or code).strip() or code
    timestamp = now_text()
    values = {
        "code": code,
        "source_code": source_code,
        "aliquot_no": None,
        "name": name,
        "category": str(data.get("category") or "临床标本").strip() or "临床标本",
        "amount": None if data.get("amount") in (None, "") else safe_float(data.get("amount"), 0),
        "amount_unit": str(data.get("amount_unit", "") or "").strip(),
        "quantity": safe_float(data.get("quantity"), 1),
        "status": str(data.get("status", STATUS_AVAILABLE)).strip() or STATUS_AVAILABLE,
        "storage_node_id": SYSTEM_UNPLACED_NODE_ID,
        "grid_cell": None,
        "entry_date": str(data.get("entry_date") or date.today().isoformat()),
        "note": str(data.get("note", "")).strip(),
        "created_by": user["id"],
        "updated_by": user["id"],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if values["status"] not in dropdown_values("sample_statuses"):
        raise ApiError(400, "标本状态不正确")
    return values


def create_sample(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    values = base_sample_values(data, user)
    tube_count = clean_int_range(data.get("tube_count"), 1, 1, 300)
    separate_items = bool(data.get("separate_items", True))
    node_id = clean_optional_positive_int(data.get("storage_node_id"))
    start_position = str(data.get("grid_cell", "")).strip() or None
    with connect() as conn:
        if separate_items:
            items = insert_sample_tubes(conn, values, tube_count, user["id"], node_id, start_position)
        else:
            items = insert_combined_sample(conn, values, tube_count, user["id"], node_id, start_position)
        create_audit(conn, user["id"], "api_create_clinical_sample", "clinical_samples", items[0]["id"], data, None)
        conn.commit()
    return {"item": items[0], "items": items, "count": len(items)}


def update_sample(sample_id: int, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "code", "source_code", "name", "category", "amount", "amount_unit", "quantity", "status",
        "storage_node_id", "grid_cell", "entry_date", "note",
    ]
    move_node_requested = "storage_node_id" in data
    move_node_id = data.get("storage_node_id") if move_node_requested else None
    move_position = data.get("grid_cell", "")
    updates = {key: data[key] for key in allowed if key in data and key not in {"storage_node_id", "grid_cell"}}
    if not updates and not move_node_requested:
        raise ApiError(400, "没有可更新字段")
    if "name" in updates and not str(updates["name"]).strip():
        raise ApiError(400, "样本号不能为空")
    if "amount" in updates:
        updates["amount"] = None if updates["amount"] in (None, "") else safe_float(updates["amount"], 0)
    if "amount_unit" in updates:
        updates["amount_unit"] = str(updates["amount_unit"] or "").strip()
    if "status" in updates:
        updates["status"] = str(updates["status"] or "").strip() or STATUS_AVAILABLE
        if updates["status"] not in dropdown_values("sample_statuses"):
            raise ApiError(400, "标本状态不正确")
    if "quantity" in updates:
        updates["quantity"] = safe_float(updates["quantity"], 1)
    if "code" in updates:
        updates["code"] = str(updates["code"] or "").strip()
        if not updates["code"]:
            raise ApiError(400, "编号不能为空")
    if "source_code" in updates:
        updates["source_code"] = str(updates["source_code"] or "").strip() or None
    if "name" in updates:
        updates["name"] = str(updates["name"] or "").strip()
    if "category" in updates:
        updates["category"] = str(updates["category"] or "临床标本").strip() or "临床标本"
    if "entry_date" in updates:
        updates["entry_date"] = str(updates["entry_date"] or date.today().isoformat())
    if "note" in updates:
        updates["note"] = str(updates["note"] or "").strip()
    updates["updated_by"] = user["id"]
    updates["updated_at"] = now_text()
    with connect() as conn:
        old = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
        if old is None:
            raise ApiError(404, "临床标本不存在")
        next_code = updates.get("code", old["code"])
        next_source = updates.get("source_code", old["source_code"])
        ensure_unique_sample_aliquot(conn, next_code, old["aliquot_no"], sample_id, next_source)
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(f"UPDATE clinical_samples SET {assignments} WHERE id = ?", list(updates.values()) + [sample_id])
        current = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
        if not occupies_storage(current["status"]):
            release_sample_storage(conn, sample_id, user["id"])
        else:
            current_node_id = int(current["storage_node_id"] or SYSTEM_UNPLACED_NODE_ID)
            needs_default_from_system = current_node_id <= 0 and current_node_id not in {SYSTEM_UNPLACED_NODE_ID, SYSTEM_CHECKED_OUT_NODE_ID}
            if move_node_requested or needs_default_from_system:
                target_node_id = sample_target_for_status(current["status"], move_node_id if move_node_requested else None)
                if target_node_id <= 0 and target_node_id != SYSTEM_UNPLACED_NODE_ID:
                    raise ApiError(400, "存放位置只能选择真实空间或未归位")
                target_position = str(move_position or "").strip() or None
                target_position = target_position if target_node_id > 0 else None
                from_node_id = current_node_id
                from_position = str(current["grid_cell"] or "").strip() or None
                assign_sample_to_node(conn, sample_id, target_node_id, user["id"], target_position)
                if int(from_node_id) != int(target_node_id) or str(from_position or "") != str(target_position or ""):
                    record_sample_transfer(
                        conn,
                        item_id=sample_id,
                        object_id=current["code"] or str(sample_id),
                        from_node_id=from_node_id,
                        from_position=from_position,
                        to_node_id=target_node_id,
                        to_position=target_position,
                        user_id=user["id"],
                        reason=MOVEMENT_REASON_MOVE if move_node_requested else MOVEMENT_REASON_STATUS,
                        note="标本位置已更新" if move_node_requested else "标本状态调整后自动进入未归位",
                    )
        create_audit(conn, user["id"], "api_update_clinical_sample", "clinical_samples", sample_id, data, row_dict(old))
        conn.commit()
        return {"item": sample_detail(conn, sample_id)["item"]}


def create_aliquots(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    source_id = clean_optional_positive_int(data.get("source_item_id")) or 0
    if not source_id:
        raise ApiError(400, "必须选择已有标本")
    tube_count = clean_int_range(data.get("tube_count"), 1, 1, 300)
    node_id = clean_optional_positive_int(data.get("storage_node_id"))
    start_position = str(data.get("grid_cell", "")).strip() or None
    with connect() as conn:
        source = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (source_id,)).fetchone()
        if source is None:
            raise ApiError(404, "临床标本不存在")
        if not occupies_storage(source["status"]):
            raise ApiError(409, "只有已入库标本可以分装")
        note = str(data.get("note", "")).strip()
        values = {
            "name": source["name"],
            "category": source["category"] or "临床标本",
            "source_code": source["source_code"] or source["code"],
            "amount": source["amount"] if data.get("amount") in (None, "") else safe_float(data.get("amount"), 0),
            "amount_unit": str(data.get("amount_unit", "")).strip() or source["amount_unit"],
            "status": STATUS_AVAILABLE,
            "entry_date": str(data.get("entry_date") or date.today().isoformat()),
            "note": f"由 {source['source_code'] or source['code']} 分装" + (f"；{note}" if note else ""),
        }
        base_values = base_sample_values(values, user)
        items = insert_sample_tubes(conn, base_values, tube_count, user["id"], node_id, start_position, auto_find_from_start=True)
        create_audit(conn, user["id"], "api_create_clinical_sample_aliquot", "clinical_samples", items[0]["id"], data, row_dict(source))
        conn.commit()
    return {"item": items[0], "items": items, "count": len(items)}
