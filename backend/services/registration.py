from __future__ import annotations

import base64
import io
import re
import uuid
from datetime import date, datetime
from typing import Any

from core.common import ApiError, clean_int_range, clean_optional_positive_int, create_audit, now_text, row_dict, rows_list, safe_float
from core.config import ROOT, VALIDATION_IMAGE_DIR
from core.constants import (
    MOVEMENT_REASON_ARRIVAL,
    MOVEMENT_REASON_ORDER,
    STATUS_AVAILABLE,
    STATUS_ORDERED,
    SYSTEM_NOT_ARRIVED_NODE_ID,
    SYSTEM_NOT_ORDERED_NODE_ID,
    SYSTEM_UNPLACED_NODE_ID,
)
from db.database import connect
from services.movements import record_reagent_transfer
from services.storage_inventory import (
    assign_reagent_to_node,
    sequential_frame_positions,
    storage_target_or_default,
    storage_location_text,
)

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - deployment dependency check
    Image = None
    ImageOps = None


MAX_VALIDATION_IMAGE_UPLOAD_BYTES = 12 * 1024 * 1024
TARGET_VALIDATION_IMAGE_BYTES = 1 * 1024 * 1024
MAX_VALIDATION_IMAGE_SIDE = 1800


def list_orders(query: dict[str, list[str]]) -> dict[str, Any]:
    status = query.get("status", [""])[0].strip()
    catalog_no = query.get("catalog_no", [""])[0].strip()
    clauses = ["m.reason = ?"]
    params: list[Any] = [MOVEMENT_REASON_ORDER]
    post_status = ""
    if status in {"未到货", "已到货"}:
        post_status = status
    elif status:
        clauses.append("r.status = ?")
        params.append(status)
    if catalog_no:
        clauses.append("TRIM(COALESCE(r.catalog_no, '')) = ?")
        params.append(catalog_no)
    sql = f"""
        SELECT r.*, m.id AS order_movement_id, m.note AS order_reason, m.moved_at AS ordered_at,
               m.moved_by AS requester_id, u.display_name AS requester_name
        FROM movements m
        JOIN reagents r ON r.id = m.item_id AND m.item_type = 'reagent'
        LEFT JOIN users u ON u.id = m.moved_by
        WHERE {" AND ".join(clauses)}
        ORDER BY m.moved_at DESC, m.id DESC
        LIMIT 200
    """
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        items = [_order_ledger_item(conn, row) for row in rows]
    if post_status:
        items = [item for item in items if item.get("arrival_status") == post_status]
    return {"items": items, "count": len(items)}


def _source_key(row: Any) -> str:
    return str(row["source_code"] or row["code"] or row["id"])


def _arrival_rows_for_source(conn: Any, source_key: str) -> list[Any]:
    return conn.execute(
        """
        SELECT m.*, r.code, r.name, r.quantity, r.entry_date, r.expiration_date,
               u.display_name AS received_by_name
        FROM movements m
        JOIN reagents r ON r.id = m.item_id AND m.item_type = 'reagent'
        LEFT JOIN users u ON u.id = m.moved_by
        WHERE m.reason = ?
          AND COALESCE(r.source_code, r.code, r.id) = ?
        ORDER BY m.moved_at DESC, m.id DESC
        """,
        (MOVEMENT_REASON_ARRIVAL, source_key),
    ).fetchall()


def _order_ledger_item(conn: Any, row: Any) -> dict[str, Any]:
    item = row_dict(row) or {}
    source_key = _source_key(row)
    arrivals = _arrival_rows_for_source(conn, source_key)
    arrived_quantity = sum(float(arrival["quantity"] or 0) for arrival in arrivals)
    arrival_locations = [str(arrival["to_location_snapshot"] or "") for arrival in arrivals if str(arrival["to_location_snapshot"] or "").strip()]
    arrival_dates = [str(arrival["entry_date"] or arrival["moved_at"] or "") for arrival in arrivals if str(arrival["entry_date"] or arrival["moved_at"] or "").strip()]
    expiration_dates = [str(arrival["expiration_date"] or "") for arrival in arrivals if str(arrival["expiration_date"] or "").strip()]
    receiver_names = [str(arrival["received_by_name"] or "") for arrival in arrivals if str(arrival["received_by_name"] or "").strip()]
    item.update({
        "id": item.get("id"),
        "requester_id": item.get("requester_id"),
        "reason": item.get("order_reason") or item.get("note") or "",
        "created_at": item.get("ordered_at") or item.get("created_at"),
        "updated_at": item.get("updated_at") or item.get("ordered_at"),
        "arrival_count": len(arrivals),
        "arrived_quantity": arrived_quantity,
        "arrival_status": "已到货" if arrivals else "未到货",
        "arrival_ids": "、".join(str(arrival["id"]) for arrival in arrivals),
        "arrival_codes": "、".join(str(arrival["code"] or "") for arrival in arrivals if str(arrival["code"] or "").strip()),
        "arrival_locations": "、".join(arrival_locations),
        "arrival_entry_dates": "、".join(arrival_dates),
        "arrival_expiration_dates": "、".join(expiration_dates),
        "received_by_names": "、".join(receiver_names),
        "last_arrival_at": arrivals[0]["moved_at"] if arrivals else None,
    })
    if arrivals:
        item["quantity"] = arrived_quantity or item.get("quantity")
    return item


def _ensure_reagent_code(conn: Any, reagent_id: int) -> str:
    row = conn.execute("SELECT code FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
    code = str(row["code"] or "").strip() if row else ""
    if code:
        return code
    code = f"RG{reagent_id:06d}"
    conn.execute(
        """
        UPDATE reagents
        SET code = CASE WHEN code IS NULL OR TRIM(code) = '' THEN ? ELSE code END,
            source_code = CASE WHEN source_code IS NULL OR TRIM(source_code) = '' THEN ? ELSE source_code END
        WHERE id = ?
        """,
        (code, code, reagent_id),
    )
    return code


def create_order(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ApiError(400, "订购名称不能为空")
    timestamp = now_text()
    values = {
        "code": None,
        "source_code": None,
        "aliquot_no": None,
        "name": name,
        "category": str(data.get("category", "")).strip(),
        "brand": str(data.get("brand", "")).strip(),
        "catalog_no": str(data.get("catalog_no", "")).strip(),
        "amount": None if data.get("amount") in (None, "") else safe_float(data.get("amount"), 0),
        "amount_unit": str(data.get("amount_unit", "")).strip(),
        "quantity": safe_float(data.get("quantity"), 1),
        "price": None if data.get("price") in (None, "") else safe_float(data.get("price"), 0),
        "status": STATUS_ORDERED,
        "storage_node_id": SYSTEM_NOT_ARRIVED_NODE_ID,
        "grid_cell": None,
        "entry_date": "",
        "expiration_date": "",
        "note": str(data.get("reason", "")).strip(),
        "created_by": user["id"],
        "updated_by": user["id"],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    cols = list(values)
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO reagents ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
            [values[col] for col in cols],
        )
        reagent_id = int(cur.lastrowid)
        code = f"RG{reagent_id:06d}"
        conn.execute("UPDATE reagents SET code = ?, source_code = ? WHERE id = ?", (code, code, reagent_id))
        movement_id = record_reagent_transfer(
            conn,
            object_id=code,
            item_id=reagent_id,
            from_node_id=SYSTEM_NOT_ORDERED_NODE_ID,
            from_position=None,
            to_node_id=SYSTEM_NOT_ARRIVED_NODE_ID,
            to_position=None,
            user_id=user["id"],
            moved_at=timestamp,
            reason=MOVEMENT_REASON_ORDER,
            note=str(data.get("reason", "")).strip(),
        )
        create_audit(conn, user["id"], "api_create_order", "reagents", reagent_id, data)
        conn.commit()
        row = conn.execute(
            """
            SELECT r.*, m.id AS order_movement_id, m.note AS order_reason, m.moved_at AS ordered_at,
                   m.moved_by AS requester_id, u.display_name AS requester_name
            FROM movements m
            JOIN reagents r ON r.id = m.item_id AND m.item_type = 'reagent'
            LEFT JOIN users u ON u.id = m.moved_by
            WHERE m.id = ?
            """,
            (movement_id,),
        ).fetchone()
        item = _order_ledger_item(conn, row)
    return {"item": item}


def clean_arrival_count(value: Any, fallback: Any = 1) -> int:
    try:
        default = int(float(fallback or 1))
    except (TypeError, ValueError):
        default = 1
    return clean_int_range(value, default, 1, 300)


def create_arrival(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    order_id = clean_optional_positive_int(data.get("order_id")) or 0
    if not order_id:
        raise ApiError(400, "必须选择订购登记")
    entry_date = str(data.get("entry_date") or date.today().isoformat())
    expiration_date = str(data.get("expiration_date", "")).strip() or None
    note = str(data.get("note", "")).strip()
    position = str(data.get("grid_cell", "")).strip() or None
    with connect() as conn:
        order = conn.execute("SELECT * FROM reagents WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise ApiError(404, "订购登记不存在")
        order_movement = conn.execute(
            "SELECT * FROM movements WHERE item_type = 'reagent' AND item_id = ? AND reason = ? ORDER BY id LIMIT 1",
            (order_id, MOVEMENT_REASON_ORDER),
        ).fetchone()
        if order_movement is None:
            raise ApiError(404, "订购登记不存在")
        if str(order["status"] or "") != STATUS_ORDERED or int(order["storage_node_id"] or 0) != SYSTEM_NOT_ARRIVED_NODE_ID:
            raise ApiError(409, "该订购登记不是未到货状态")
        arrived = conn.execute(
            """
            SELECT 1
            FROM movements m JOIN reagents r ON r.id = m.item_id AND m.item_type = 'reagent'
            WHERE m.reason = ? AND COALESCE(r.source_code, r.code, r.id) = ?
            LIMIT 1
            """,
            (MOVEMENT_REASON_ARRIVAL, _source_key(order)),
        ).fetchone()
        if arrived:
            raise ApiError(409, "该订购登记已登记到货")
        timestamp = now_text()
        arrival_count = clean_arrival_count(data.get("arrival_quantity"), order["quantity"])
        separate_items = bool(data.get("separate_items", True))
        row_count = arrival_count if separate_items else 1
        storage_node_id = storage_target_or_default(data.get("storage_node_id"), STATUS_AVAILABLE)
        if storage_node_id != SYSTEM_UNPLACED_NODE_ID and storage_node_id <= 0:
            raise ApiError(400, "到货位置只能选择真实空间或未归位")
        real_storage = storage_node_id > 0
        positions = sequential_frame_positions(conn, storage_node_id, row_count, position) if real_storage and row_count > 1 else [position if real_storage else None] * row_count
        reagent_ids: list[int] = []
        arrival_rows: list[dict[str, Any]] = []
        source_code = str(order["source_code"] or order["code"] or "").strip()
        if not source_code:
            source_code = _ensure_reagent_code(conn, order_id)
        for index in range(row_count):
            aliquot_no = index + 1 if row_count > 1 else None
            row_quantity = 1 if separate_items else arrival_count
            if index == 0:
                reagent_id = order_id
                code = _ensure_reagent_code(conn, reagent_id)
                conn.execute(
                    """
                    UPDATE reagents
                    SET source_code = ?, aliquot_no = ?, quantity = ?, status = ?, entry_date = ?,
                        expiration_date = ?, note = ?, updated_by = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (source_code, aliquot_no, row_quantity, STATUS_AVAILABLE, entry_date, expiration_date, note, user["id"], timestamp, reagent_id),
                )
            else:
                values = {
                    "code": None,
                    "source_code": source_code,
                    "aliquot_no": aliquot_no,
                    "name": order["name"],
                    "category": order["category"] or "其他",
                    "brand": order["brand"] or "",
                    "catalog_no": order["catalog_no"] or "",
                    "amount": order["amount"],
                    "amount_unit": order["amount_unit"] or "",
                    "quantity": row_quantity,
                    "price": order["price"],
                    "status": STATUS_AVAILABLE,
                    "storage_node_id": SYSTEM_NOT_ARRIVED_NODE_ID,
                    "grid_cell": None,
                    "entry_date": entry_date,
                    "expiration_date": expiration_date,
                    "note": note,
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
                code = f"RG{reagent_id:06d}"
                conn.execute("UPDATE reagents SET code = ? WHERE id = ?", (code, reagent_id))
            reagent_ids.append(reagent_id)
            assign_reagent_to_node(conn, reagent_id, storage_node_id, user["id"], positions[index])
            storage_location = storage_location_text(conn, storage_node_id, positions[index])
            movement_id = record_reagent_transfer(
                conn,
                object_id=code,
                item_id=reagent_id,
                from_node_id=SYSTEM_NOT_ARRIVED_NODE_ID,
                from_position=None,
                to_node_id=storage_node_id,
                to_position=positions[index],
                user_id=user["id"],
                moved_at=timestamp,
                reason=MOVEMENT_REASON_ARRIVAL,
                note=note,
            )
            arrival_item = {
                "id": movement_id,
                "order_id": order_id,
                "item_type": "reagent",
                "item_id": reagent_id,
                "entry_date": entry_date,
                "received_by": user["id"],
                "storage_node_id": storage_node_id,
                "grid_cell": positions[index],
                "location_snapshot": storage_location,
                "storage_location": storage_location,
                "expiration_date": expiration_date,
                "note": note,
                "created_at": timestamp,
                "code": code,
                "name": order["name"],
            }
            arrival_rows.append(arrival_item)
        create_audit(conn, user["id"], "api_create_arrival", "movements", arrival_rows[0]["id"], {"order_id": order_id, "item_type": "reagent", "item_ids": reagent_ids, "arrival_quantity": arrival_count, "separate_items": separate_items})
        conn.commit()
    return {"item": arrival_rows[0], "items": arrival_rows, "count": len(arrival_rows), "item_type": "reagent", "item_id": reagent_ids[0], "item_ids": reagent_ids}


VALIDATION_SELECT_SQL = """
    SELECT
        v.id, NULL AS item_id, v.catalog_no,
        v.validator_id, v.validation_date, v.method, v.result, v.description, v.image_path, v.created_at,
        r.code, r.name, u.display_name AS validator_name
    FROM validations v
    LEFT JOIN (
        SELECT catalog_no, MIN(code) AS code, MIN(name) AS name
        FROM reagents
        WHERE COALESCE(catalog_no, '') != ''
        GROUP BY catalog_no
    ) r ON r.catalog_no = v.catalog_no
    LEFT JOIN users u ON u.id = v.validator_id
"""


def list_validations() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(f"{VALIDATION_SELECT_SQL} ORDER BY v.created_at DESC LIMIT 200").fetchall()
    return {"items": rows_list(rows), "count": len(rows)}


def create_validation(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    catalog_no = str(data.get("catalog_no") or "").strip()
    result = str(data.get("result", "")).strip()
    if not result:
        raise ApiError(400, "验证结果不能为空")
    timestamp = now_text()
    with connect() as conn:
        if not catalog_no:
            raise ApiError(400, "验证登记必须填写货号")
        cur = conn.execute(
            """
            INSERT INTO validations (catalog_no, validator_id, validation_date, method, result, description, image_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                catalog_no, user["id"], str(data.get("validation_date") or date.today().isoformat()),
                str(data.get("method", "")).strip(), result, str(data.get("description", "")).strip(),
                str(data.get("image_path", "")).strip(), timestamp,
            ),
        )
        create_audit(conn, user["id"], "api_create_validation", "validations", cur.lastrowid, data)
        conn.commit()
        row = _validation_public_row(conn, int(cur.lastrowid))
    return {"item": row_dict(row)}


def update_validation(validation_id: int, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    allowed = {"catalog_no", "validation_date", "method", "result", "description", "image_path"}
    updates = {key: data[key] for key in allowed if key in data}
    if not updates:
        raise ApiError(400, "没有可更新字段")
    if "catalog_no" in updates:
        updates["catalog_no"] = str(updates["catalog_no"] or "").strip()
        if not updates["catalog_no"]:
            raise ApiError(400, "验证登记必须填写货号")
    if "result" in updates:
        updates["result"] = str(updates["result"] or "").strip()
        if not updates["result"]:
            raise ApiError(400, "验证结果不能为空")
    for key in ("validation_date", "method", "description", "image_path"):
        if key in updates:
            updates[key] = str(updates[key] or "").strip()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with connect() as conn:
        old = conn.execute("SELECT * FROM validations WHERE id = ?", (validation_id,)).fetchone()
        if old is None:
            raise ApiError(404, "验证记录不存在")
        if user.get("role") != "admin" and int(old["validator_id"] or 0) != int(user["id"]):
            raise ApiError(403, "只能编辑自己登记的验证记录")
        conn.execute(f"UPDATE validations SET {assignments} WHERE id = ?", list(updates.values()) + [validation_id])
        create_audit(conn, user["id"], "api_update_validation", "validations", validation_id, updates, row_dict(old))
        conn.commit()
        row = _validation_public_row(conn, validation_id)
    return {"item": row_dict(row)}


def _validation_public_row(conn: Any, validation_id: int) -> Any:
    return conn.execute(f"{VALIDATION_SELECT_SQL} WHERE v.id = ?", (validation_id,)).fetchone()


def upload_validation_image(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    file_data = str(data.get("data_url", ""))
    code = _safe_filename_part(str(data.get("code", "item")))
    method = _safe_filename_part(str(data.get("method", "method")))
    validation_date = _safe_filename_part(str(data.get("validation_date", date.today().isoformat())))
    body = _parse_image_data_url(file_data)
    if len(body) > MAX_VALIDATION_IMAGE_UPLOAD_BYTES:
        raise ApiError(400, "图片不能超过 12MB")
    body, ext = _compress_validation_image(body)
    VALIDATION_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{code}_{validation_date}_{method}_{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    path = VALIDATION_IMAGE_DIR / filename
    path.write_bytes(body)
    rel_path = path.relative_to(ROOT).as_posix()
    with connect() as conn:
        create_audit(conn, user["id"], "api_upload_validation_image", "validation_images", None, {"path": rel_path})
        conn.commit()
    return {"path": rel_path, "size": len(body)}


def _parse_image_data_url(value: str) -> bytes:
    if not value.startswith("data:") or "," not in value:
        raise ApiError(400, "图片数据格式不正确")
    header, payload = value.split(",", 1)
    mime = header.removeprefix("data:").split(";", 1)[0].lower()
    if mime not in {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/tiff"}:
        raise ApiError(400, "只支持 png、jpg、webp、tif 图片")
    try:
        return base64.b64decode(payload)
    except Exception as exc:
        raise ApiError(400, "图片数据无法解析") from exc


def _compress_validation_image(body: bytes) -> tuple[bytes, str]:
    if Image is None or ImageOps is None:
        raise ApiError(500, "服务器缺少 Pillow，无法压缩图片")
    try:
        image = Image.open(io.BytesIO(body))
        image = ImageOps.exif_transpose(image)
    except Exception as exc:
        raise ApiError(400, "图片文件无法读取") from exc
    if image.mode not in ("RGB", "L"):
        background = Image.new("RGB", image.size, "white")
        if image.mode in ("RGBA", "LA"):
            background.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
        else:
            background.paste(image.convert("RGB"))
        image = background
    else:
        image = image.convert("RGB")

    max_side = MAX_VALIDATION_IMAGE_SIDE
    quality = 88
    while True:
        candidate = image.copy()
        candidate.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        for q in range(quality, 39, -7):
            output = io.BytesIO()
            candidate.save(output, format="JPEG", quality=q, optimize=True, progressive=True)
            compressed = output.getvalue()
            if len(compressed) <= TARGET_VALIDATION_IMAGE_BYTES:
                return compressed, ".jpg"
        if max_side <= 640:
            break
        max_side = int(max_side * 0.82)
        quality = 78
    raise ApiError(400, f"图片压缩后仍超过 {TARGET_VALIDATION_IMAGE_BYTES // 1024 // 1024}MB，请裁剪后再上传")


def _safe_filename_part(value: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value.strip(), flags=re.UNICODE).strip("_")
    return text[:80] or "file"
