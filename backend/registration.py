from __future__ import annotations

import base64
import io
import re
import uuid
from datetime import date, datetime
from typing import Any

from common import ApiError, create_audit, now_text, row_dict, rows_list, safe_float
from config import ROOT, VALIDATION_IMAGE_DIR
from database import connect
from storage_inventory import (
    assign_reagent_to_node,
    sequential_box_positions,
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
    clauses = []
    params: list[Any] = []
    if status:
        if status in {"未到货", "已到货"}:
            clauses.append("(CASE WHEN COALESCE(a.arrival_count, 0) > 0 THEN '已到货' ELSE '未到货' END) = ?")
        else:
            clauses.append("o.status = ?")
        params.append(status)
    sql = """
        SELECT o.*, u.display_name AS requester_name,
               COALESCE(a.arrival_count, 0) AS arrival_count,
               CASE WHEN COALESCE(a.arrival_count, 0) > 0 THEN '已到货' ELSE '未到货' END AS arrival_status
        FROM orders o LEFT JOIN users u ON u.id = o.requester_id
        LEFT JOIN (
            SELECT order_id, COUNT(*) AS arrival_count
            FROM arrivals
            WHERE order_id IS NOT NULL
            GROUP BY order_id
        ) a ON a.order_id = o.id
    """
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY o.updated_at DESC LIMIT 200"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {"items": rows_list(rows), "count": len(rows)}


def create_order(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    if not name:
        raise ApiError(400, "订购名称不能为空")
    timestamp = now_text()
    values = {
        "requester_id": user["id"],
        "name": name,
        "category": str(data.get("category", "")).strip(),
        "brand": str(data.get("brand", "")).strip(),
        "catalog_no": str(data.get("catalog_no", "")).strip(),
        "amount": None if data.get("amount") in (None, "") else safe_float(data.get("amount"), 0),
        "amount_unit": str(data.get("amount_unit", "")).strip(),
        "quantity": safe_float(data.get("quantity"), 1),
        "reason": str(data.get("reason", "")).strip(),
        "price": None if data.get("price") in (None, "") else safe_float(data.get("price"), 0),
        "status": "已订购",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    cols = list(values)
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO orders ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})",
            [values[col] for col in cols],
        )
        create_audit(conn, user["id"], "api_create_order", "orders", cur.lastrowid, data)
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"item": row_dict(row)}


def clean_arrival_count(value: Any, fallback: Any = 1) -> int:
    raw = fallback if value in (None, "") else value
    try:
        count = int(float(raw))
    except (TypeError, ValueError):
        count = 1
    return max(1, min(count, 300))


def update_order(order_id: int, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    status = str(data.get("status", "")).strip()
    if status not in {"已订购", "停用"}:
        raise ApiError(400, "没有可更新字段")
    with connect() as conn:
        old = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if old is None:
            raise ApiError(404, "订购登记不存在")
        conn.execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (status, now_text(), order_id))
        create_audit(conn, user["id"], "api_update_order", "orders", order_id, data, row_dict(old))
        conn.commit()
        row = conn.execute(
            """
            SELECT o.*, u.display_name AS requester_name,
                   COALESCE(a.arrival_count, 0) AS arrival_count,
                   CASE WHEN COALESCE(a.arrival_count, 0) > 0 THEN '已到货' ELSE '未到货' END AS arrival_status
            FROM orders o LEFT JOIN users u ON u.id = o.requester_id
            LEFT JOIN (
                SELECT order_id, COUNT(*) AS arrival_count
                FROM arrivals
                WHERE order_id IS NOT NULL
                GROUP BY order_id
            ) a ON a.order_id = o.id
            WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()
    return {"item": row_dict(row)}


def list_arrivals() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*, a.location_snapshot AS storage_location,
                   r.code, r.name, u.display_name AS received_by_name
            FROM arrivals a
            LEFT JOIN reagents r ON r.id = a.item_id AND a.item_type = 'reagent'
            LEFT JOIN users u ON u.id = a.received_by
            ORDER BY a.created_at DESC LIMIT 200
            """
        ).fetchall()
    return {"items": rows_list(rows), "count": len(rows)}


def create_arrival(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    order_id = int(data.get("order_id") or 0)
    storage_node_id = int(data.get("storage_node_id") or 0) or None
    if not order_id:
        raise ApiError(400, "必须选择订购登记")
    entry_date = str(data.get("entry_date") or date.today().isoformat())
    expiration_date = str(data.get("expiration_date", "")).strip() or None
    note = str(data.get("note", "")).strip()
    position = str(data.get("position_in_box", "")).strip() or None
    with connect() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise ApiError(404, "订购登记不存在")
        arrived = conn.execute("SELECT 1 FROM arrivals WHERE order_id = ? LIMIT 1", (order_id,)).fetchone()
        if arrived:
            raise ApiError(409, "该订购登记已登记到货")
        timestamp = now_text()
        arrival_count = clean_arrival_count(data.get("arrival_quantity"), order["quantity"])
        separate_items = bool(data.get("separate_items", True))
        row_count = arrival_count if separate_items else 1
        positions = sequential_box_positions(conn, storage_node_id, row_count, position) if storage_node_id and row_count > 1 else [position if storage_node_id else None] * row_count
        reagent_ids: list[int] = []
        arrival_rows: list[dict[str, Any]] = []
        source_code = None
        for index in range(row_count):
            aliquot_no = index + 1 if row_count > 1 else None
            row_quantity = 1 if separate_items else arrival_count
            cur = conn.execute(
                """
                INSERT INTO reagents
                    (code, source_code, aliquot_no, name, category, brand, catalog_no, amount, amount_unit, quantity, status,
                     entry_date, expiration_date, validation_status, note, created_by, updated_by, created_at, updated_at)
                VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, '可用', ?, ?, '未验证', ?, ?, ?, ?, ?)
                """,
                (
                    source_code, aliquot_no,
                    order["name"], order["category"] or "其他", order["brand"] or "", order["catalog_no"] or "",
                    order["amount"], order["amount_unit"] or "", row_quantity, entry_date, expiration_date, note, user["id"], user["id"], timestamp, timestamp,
                ),
            )
            reagent_id = int(cur.lastrowid)
            reagent_ids.append(reagent_id)
            code = f"RG{reagent_id:06d}"
            if row_count > 1 and source_code is None:
                source_code = code
                conn.execute(
                    "UPDATE reagents SET code = ?, source_code = ? WHERE id = ?",
                    (code, source_code, reagent_id),
                )
            else:
                conn.execute("UPDATE reagents SET code = ?, source_code = COALESCE(source_code, ?) WHERE id = ?", (code, source_code or code, reagent_id))
            if storage_node_id:
                assign_reagent_to_node(conn, reagent_id, storage_node_id, user["id"], positions[index])
            storage_location = storage_location_text(conn, storage_node_id, positions[index]) if storage_node_id else "未归位"
            arrival = conn.execute(
                """
                INSERT INTO arrivals
                    (order_id, item_type, item_id, entry_date, received_by, storage_node_id, position_in_box,
                     location_snapshot, expiration_date, note, created_at)
                VALUES (?, 'reagent', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (order_id, reagent_id, entry_date, user["id"], storage_node_id, positions[index], storage_location, expiration_date, note, timestamp),
            )
            row = conn.execute("SELECT * FROM arrivals WHERE id = ?", (arrival.lastrowid,)).fetchone()
            arrival_item = row_dict(row) or {}
            arrival_item["storage_location"] = arrival_item.get("location_snapshot") or ""
            arrival_rows.append(arrival_item)
        conn.execute("UPDATE orders SET updated_at = ? WHERE id = ?", (timestamp, order_id))
        create_audit(conn, user["id"], "api_create_arrival", "arrivals", arrival_rows[0]["id"], {"order_id": order_id, "item_type": "reagent", "item_ids": reagent_ids, "arrival_quantity": arrival_count, "separate_items": separate_items})
        conn.commit()
    return {"item": arrival_rows[0], "items": arrival_rows, "count": len(arrival_rows), "item_type": "reagent", "item_id": reagent_ids[0], "item_ids": reagent_ids}


def list_validations() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            """
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
            ORDER BY v.created_at DESC LIMIT 200
            """
        ).fetchall()
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
        conn.execute("UPDATE reagents SET validation_status = ?, updated_by = ?, updated_at = ? WHERE catalog_no = ?", (result, user["id"], timestamp, catalog_no))
        create_audit(conn, user["id"], "api_create_validation", "validations", cur.lastrowid, data)
        conn.commit()
        row = conn.execute(
            """
            SELECT
                v.id, NULL AS item_id, v.catalog_no,
                v.validator_id, v.validation_date, v.method, v.result, v.description, v.image_path, v.created_at,
                r.code, r.name
            FROM validations v
            LEFT JOIN (
                SELECT catalog_no, MIN(code) AS code, MIN(name) AS name
                FROM reagents
                WHERE COALESCE(catalog_no, '') != ''
                GROUP BY catalog_no
            ) r ON r.catalog_no = v.catalog_no
            WHERE v.id = ?
            """,
            (cur.lastrowid,),
        ).fetchone()
    return {"item": row_dict(row)}


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
