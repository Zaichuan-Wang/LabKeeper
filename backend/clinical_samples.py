from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from common import ApiError, create_audit, now_text, row_dict, safe_float
from database import connect
from options_config import dropdown_values
from storage_inventory import (
    assign_sample_to_node,
    attach_aliquot_totals,
    descendant_node_ids,
    normalize_sample_item,
    occupies_storage,
    release_sample_storage,
    sequential_box_positions,
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


def clean_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def clean_count(value: Any, default: int = 1) -> int:
    number = clean_optional_int(value)
    return min(number or default, 300)


def normalize_sample_rows(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return attach_aliquot_totals(conn, [normalize_sample_item(row, conn) for row in rows])


def list_samples(query: dict[str, list[str]]) -> dict[str, Any]:
    keyword = query.get("keyword", [""])[0].strip()
    name = query.get("name", [""])[0].strip()
    category = query.get("category", [""])[0].strip()
    status = query.get("status", [""])[0].strip()
    storage_node_id = int(query.get("storage_node_id", ["0"])[0] or 0)
    include_descendants = query.get("include_descendants", ["1"])[0] != "0"
    limit = min(int(query.get("limit", ["200"])[0] or 200), 500)
    clauses: list[str] = []
    params: list[Any] = []
    if keyword:
        clauses.append(
            """
            (code LIKE ? OR name LIKE ? OR category LIKE ? OR note LIKE ?
             OR CAST(aliquot_no AS TEXT) LIKE ?)
            """
        )
        params.extend([f"%{keyword}%"] * 5)
    if name:
        clauses.append("name = ?")
        params.append(name)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if status:
        clauses.append("status = ?")
        params.append(status)
    with connect() as conn:
        if storage_node_id:
            node_ids = descendant_node_ids(conn, storage_node_id, True) if include_descendants else [storage_node_id]
            placeholders = ",".join("?" for _ in node_ids)
            clauses.append(f"storage_node_id IN ({placeholders})")
            params.extend(node_ids)
        sql = "SELECT * FROM clinical_samples"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        items = normalize_sample_rows(conn, rows)
        if keyword:
            lowered = keyword.lower()
            items = [
                item for item in items
                if lowered in str(item.get("storage_location") or "").lower()
                or any(lowered in str(item.get(key) or "").lower() for key in ("code", "name", "category", "note", "aliquot_no"))
            ]
    return {"items": items, "count": len(items)}


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
    if not values["source_code"]:
        values["code"] = values["code"] or next_code(conn)
        values["source_code"] = values["code"]
    first_aliquot = next_aliquot_no(conn, values["source_code"])
    if node_id and occupies_storage(values["status"]) and (tube_count > 1 or auto_find_from_start):
        positions = sequential_box_positions(conn, node_id, tube_count, start_position)
    elif node_id and occupies_storage(values["status"]):
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
        if node_id and occupies_storage(row_values["status"]):
            assign_sample_to_node(conn, sample_id, node_id, user_id, positions[offset])
        row = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
        inserted.append(normalize_sample_item(row, conn))
    return attach_aliquot_totals(conn, inserted)


def insert_combined_sample(
    conn: sqlite3.Connection,
    values: dict[str, Any],
    quantity: int,
    user_id: int,
    node_id: int | None,
    start_position: str | None,
) -> list[dict[str, Any]]:
    row_values = values.copy()
    row_values["code"] = row_values["code"] or next_code(conn)
    row_values["source_code"] = row_values["source_code"] or row_values["code"]
    row_values["quantity"] = quantity
    row_values["aliquot_no"] = None
    ensure_unique_sample_aliquot(conn, row_values["code"], row_values["aliquot_no"], source_code=row_values["source_code"])
    cols = list(row_values.keys())
    cur = conn.execute(
        f"INSERT INTO clinical_samples ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
        [row_values[col] for col in cols],
    )
    sample_id = int(cur.lastrowid)
    if node_id and occupies_storage(row_values["status"]):
        assign_sample_to_node(conn, sample_id, node_id, user_id, start_position)
    row = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (sample_id,)).fetchone()
    return attach_aliquot_totals(conn, [normalize_sample_item(row, conn)])


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
        "status": str(data.get("status", "可用")).strip() or "可用",
        "storage_node_id": None,
        "position_in_box": None,
        "entry_date": str(data.get("entry_date") or date.today().isoformat()),
        "expiration_date": str(data.get("expiration_date") or "").strip(),
        "validation_status": str(data.get("validation_status") or "").strip(),
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
    tube_count = clean_count(data.get("tube_count"), 1)
    separate_items = bool(data.get("separate_items", True))
    node_id = int(data.get("storage_node_id") or 0) or None
    start_position = str(data.get("position_in_box", "")).strip() or None
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
        "storage_node_id", "position_in_box", "entry_date", "expiration_date", "validation_status", "note",
    ]
    move_node_requested = "storage_node_id" in data
    move_node_id = data.get("storage_node_id") if move_node_requested else None
    move_position = data.get("position_in_box", "")
    updates = {key: data[key] for key in allowed if key in data and key not in {"storage_node_id", "position_in_box"}}
    if not updates and not move_node_requested:
        raise ApiError(400, "没有可更新字段")
    if "name" in updates and not str(updates["name"]).strip():
        raise ApiError(400, "样本号不能为空")
    if "amount" in updates:
        updates["amount"] = None if updates["amount"] in (None, "") else safe_float(updates["amount"], 0)
    if "amount_unit" in updates:
        updates["amount_unit"] = str(updates["amount_unit"] or "").strip()
    if "status" in updates:
        updates["status"] = str(updates["status"] or "").strip() or "可用"
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
        elif move_node_requested:
            target_node_id = int(move_node_id or 0) or None
            assign_sample_to_node(conn, sample_id, target_node_id, user["id"], str(move_position or "").strip() or None)
        create_audit(conn, user["id"], "api_update_clinical_sample", "clinical_samples", sample_id, data, row_dict(old))
        conn.commit()
        return {"item": sample_detail(conn, sample_id)["item"]}


def create_aliquots(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    source_id = int(data.get("source_item_id") or 0)
    if not source_id:
        raise ApiError(400, "必须选择已有标本")
    tube_count = clean_count(data.get("tube_count"), 1)
    node_id = int(data.get("storage_node_id") or 0) or None
    start_position = str(data.get("position_in_box", "")).strip() or None
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
            "status": "可用",
            "entry_date": str(data.get("entry_date") or date.today().isoformat()),
            "note": f"由 {source['source_code'] or source['code']} 分装" + (f"；{note}" if note else ""),
        }
        base_values = base_sample_values(values, user)
        items = insert_sample_tubes(conn, base_values, tube_count, user["id"], node_id, start_position, auto_find_from_start=True)
        create_audit(conn, user["id"], "api_create_clinical_sample_aliquot", "clinical_samples", items[0]["id"], data, row_dict(source))
        conn.commit()
    return {"item": items[0], "items": items, "count": len(items)}
