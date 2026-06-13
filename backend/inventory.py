from __future__ import annotations

import sqlite3
from typing import Any

from common import ApiError
from database import connect
from storage_inventory import attach_aliquot_totals, descendant_node_ids, node_full_path, normalize_reagent_item, normalize_sample_item
import clinical_samples
import reagents


def clean_item_type(value: Any) -> str:
    item_type = str(value or "").strip().lower().replace("_", "-")
    if item_type in {"reagent", "reagents", "试剂", "耗材", "试剂/耗材"}:
        return "reagent"
    if item_type in {"sample", "samples", "clinical-sample", "clinical-samples", "临床标本", "标本"}:
        return "sample"
    raise ApiError(400, "库存类型不正确")


def _copy_present(data: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
    if key in data:
        payload[key] = data[key]


def reagent_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in (
        "code", "source_code", "name", "category", "brand", "catalog_no", "amount", "amount_unit",
        "quantity", "status", "entry_date", "expiration_date", "validation_status",
        "storage_node_id", "position_in_box", "separate_items", "note",
    ):
        _copy_present(data, key, payload)
    return payload


def sample_payload(data: dict[str, Any]) -> dict[str, Any]:
    if str(data.get("brand") or "").strip() or str(data.get("catalog_no") or "").strip():
        raise ApiError(400, "临床标本不填写品牌或货号")
    payload: dict[str, Any] = {}
    for key in (
        "code", "source_code", "name", "category", "tube_count", "amount", "amount_unit",
        "quantity", "status", "entry_date", "expiration_date", "validation_status",
        "storage_node_id", "position_in_box", "separate_items", "note",
    ):
        _copy_present(data, key, payload)
    return payload


def create_item(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    item_type = clean_item_type(data.get("item_type"))
    if item_type == "sample":
        return clinical_samples.create_sample(sample_payload(data), user)
    return reagents.create_reagent(reagent_payload(data), user)


def item_detail(item_type: str, item_id: int) -> dict[str, Any]:
    clean_type = clean_item_type(item_type)
    if clean_type == "sample":
        return clinical_samples.get_sample(item_id)
    return reagents.reagent_detail(item_id)


def update_item(item_type: str, item_id: int, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    clean_type = clean_item_type(item_type)
    if clean_type == "sample":
        return clinical_samples.update_sample(item_id, sample_payload(data), user)
    return reagents.update_reagent(item_id, reagent_payload(data), user)


def _query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    return query.get(key, [default])[0].strip()


def _clean_type(value: str) -> str:
    raw = (value or "all").strip().lower().replace("_", "-")
    if raw in {"space", "spaces", "storage", "node", "nodes"}:
        return "space"
    if raw in {"sample", "samples", "clinical-sample", "clinical-samples"}:
        return "sample"
    if raw in {"reagent", "reagents"}:
        return "reagent"
    return "all"


def _clean_limit(value: str) -> int:
    try:
        limit = int(value or 80)
    except ValueError:
        limit = 80
    return max(1, min(limit, 500))


def _storage_clause(
    conn: sqlite3.Connection,
    query: dict[str, list[str]],
    clauses: list[str],
    params: list[Any],
) -> None:
    storage_node_id = int(_query_value(query, "storage_node_id", "0") or 0)
    if not storage_node_id:
        return
    include_descendants = _query_value(query, "include_descendants", "1") != "0"
    node_ids = descendant_node_ids(conn, storage_node_id, True) if include_descendants else [storage_node_id]
    placeholders = ",".join("?" for _ in node_ids)
    clauses.append(f"storage_node_id IN ({placeholders})")
    params.extend(node_ids)


def _keyword_node_ids(conn: sqlite3.Connection, keyword: str) -> list[int]:
    if not keyword:
        return []
    lowered = keyword.lower()
    ids: set[int] = set()
    rows = conn.execute("SELECT id, name, location_code, node_type, note FROM storage_nodes ORDER BY id LIMIT 1000").fetchall()
    for row in rows:
        path = node_full_path(conn, int(row["id"]))
        haystack = " ".join(str(value or "") for value in (row["name"], row["location_code"], row["node_type"], row["note"], path)).lower()
        if lowered in haystack:
            ids.update(descendant_node_ids(conn, int(row["id"]), True))
    return sorted(ids)


def _search_reagents(
    conn: sqlite3.Connection,
    query: dict[str, list[str]],
    keyword: str,
    available_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    category = _query_value(query, "category")
    if category:
        clauses.append("category = ?")
        params.append(category)
    status = _query_value(query, "status")
    if status:
        clauses.append("status = ?")
        params.append(status)
    if available_only:
        clauses.append("COALESCE(status, '') IN ('可用', '停用')")
    if keyword:
        like = f"%{keyword}%"
        keyword_nodes = _keyword_node_ids(conn, keyword)
        node_clause = ""
        if keyword_nodes:
            placeholders = ",".join("?" for _ in keyword_nodes)
            node_clause = f" OR storage_node_id IN ({placeholders})"
        clauses.append(
            f"""
            (
              name LIKE ? OR code LIKE ? OR source_code LIKE ? OR
              catalog_no LIKE ? OR brand LIKE ? OR category LIKE ? OR amount LIKE ? OR amount_unit LIKE ? OR
              note LIKE ? OR position_in_box LIKE ?{node_clause}
            )
            """
        )
        params.extend([like] * 10)
        params.extend(keyword_nodes)
    validation_status = _query_value(query, "validation_status")
    if validation_status:
        clauses.append("validation_status = ?")
        params.append(validation_status)
    _storage_clause(conn, query, clauses, params)
    sql = "SELECT * FROM reagents"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql_limit = min(limit * 10, 1000) if keyword else limit
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    rows = conn.execute(sql, [*params, sql_limit]).fetchall()
    items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn) for row in rows])
    if keyword:
        lowered = keyword.lower()
        items = [
            item for item in items
            if lowered in str(item.get("storage_location") or "").lower()
            or any(lowered in str(item.get(key) or "").lower() for key in ("name", "code", "source_code", "catalog_no", "brand", "category", "amount", "amount_unit", "note"))
        ]
    return [_with_display_fields(item) for item in items[:limit]]


def _search_samples(
    conn: sqlite3.Connection,
    query: dict[str, list[str]],
    keyword: str,
    available_only: bool,
    limit: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    name = _query_value(query, "name")
    if name:
        clauses.append("name = ?")
        params.append(name)
    category = _query_value(query, "category")
    if category:
        clauses.append("category = ?")
        params.append(category)
    status = _query_value(query, "status")
    if status:
        clauses.append("status = ?")
        params.append(status)
    if available_only:
        clauses.append("status IN ('可用', '停用')")
    if keyword:
        like = f"%{keyword}%"
        keyword_nodes = _keyword_node_ids(conn, keyword)
        node_clause = ""
        if keyword_nodes:
            placeholders = ",".join("?" for _ in keyword_nodes)
            node_clause = f" OR storage_node_id IN ({placeholders})"
        clauses.append(f"(code LIKE ? OR name LIKE ? OR category LIKE ? OR amount LIKE ? OR amount_unit LIKE ? OR note LIKE ? OR position_in_box LIKE ?{node_clause})")
        params.extend([like] * 7)
        params.extend(keyword_nodes)
    _storage_clause(conn, query, clauses, params)
    sql = "SELECT * FROM clinical_samples"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql_limit = min(limit * 10, 1000) if keyword else limit
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    rows = conn.execute(sql, [*params, sql_limit]).fetchall()
    items = attach_aliquot_totals(conn, [normalize_sample_item(row, conn) for row in rows])
    if keyword:
        lowered = keyword.lower()
        items = [
            item for item in items
            if lowered in str(item.get("storage_location") or "").lower()
            or any(lowered in str(item.get(key) or "").lower() for key in ("code", "name", "category", "amount", "amount_unit", "note", "aliquot_no"))
        ]
    return [_with_display_fields(item) for item in items[:limit]]


def _search_spaces(conn: sqlite3.Connection, keyword: str, limit: int) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if keyword:
        like = f"%{keyword}%"
        where = "WHERE name LIKE ? OR location_code LIKE ? OR node_type LIKE ? OR note LIKE ?"
        params.extend([like] * 4)
    rows = conn.execute(
        f"SELECT * FROM storage_nodes {where} ORDER BY sort_order, id LIMIT ?",
        [*params, min(limit * 10, 1000) if keyword else limit],
    ).fetchall()
    lowered = keyword.lower()
    items: list[dict[str, Any]] = []
    for row in rows:
        path = node_full_path(conn, int(row["id"]))
        haystack = " ".join(str(value or "") for value in (row["name"], row["location_code"], row["node_type"], row["note"], path)).lower()
        if lowered and lowered not in haystack:
            continue
        item = {
            "item_type": "space",
            "id": row["id"],
            "code": row["location_code"] or row["id"],
            "name": row["name"],
            "node_type": row["node_type"],
            "status": "",
            "display_title": row["name"],
            "display_subtitle": "盒子" if row["node_type"] == "box" else "普通空间",
            "display_location": path,
            "storage_location": path,
            "matched_fields": _matched_fields(keyword, {
                "空间名称": row["name"],
                "位置码": row["location_code"],
                "空间路径": path,
            }),
            "updated_at": row["updated_at"],
        }
        items.append(item)
        if len(items) >= limit:
            break
    return items


def _with_display_fields(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("item_type") == "sample":
        subtitle = " | ".join(str(part) for part in (item.get("name"), item.get("category")) if part) or "临床标本"
        item.update({
            "display_title": item.get("code") or item.get("id"),
            "display_subtitle": subtitle,
            "display_location": item.get("storage_location") or "",
        })
    else:
        parts = [item.get("category") or "试剂/耗材", item.get("brand"), f"货号 {item.get('catalog_no')}" if item.get("catalog_no") else ""]
        item.update({
            "display_title": item.get("name") or item.get("code") or item.get("id"),
            "display_subtitle": " | ".join(str(part) for part in parts if part),
            "display_location": item.get("storage_location") or "",
        })
    item["matched_fields"] = _matched_fields("", {})
    return item


def _matched_fields(keyword: str, fields: dict[str, Any]) -> list[str]:
    if not keyword:
        return []
    lowered = keyword.lower()
    return [label for label, value in fields.items() if lowered in str(value or "").lower()]


def search(query: dict[str, list[str]]) -> dict[str, Any]:
    item_type = _clean_type(_query_value(query, "type") or _query_value(query, "item_type"))
    keyword = _query_value(query, "keyword")
    available_only = _query_value(query, "available") in {"1", "true", "yes", "on"}
    limit = _clean_limit(_query_value(query, "limit", "80"))
    with connect() as conn:
        items: list[dict[str, Any]] = []
        if item_type in {"reagent", "all"}:
            items.extend(_search_reagents(conn, query, keyword, available_only, limit))
        if item_type in {"sample", "all"}:
            items.extend(_search_samples(conn, query, keyword, available_only, limit))
        if not available_only and item_type in {"space", "all"}:
            items.extend(_search_spaces(conn, keyword, limit))
    items.sort(key=lambda item: (str(item.get("updated_at") or ""), int(item.get("id") or 0)), reverse=True)
    items = items[:limit]
    return {"items": items, "count": len(items)}


def timeline(item_type: str, item_id: int) -> dict[str, Any]:
    clean_type = "sample" if item_type == "sample" else "reagent"
    with connect() as conn:
        if clean_type == "sample":
            row = conn.execute("SELECT * FROM clinical_samples WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise ApiError(404, "临床标本不存在")
            item = normalize_sample_item(row, conn)
            events = _sample_events(conn, row)
            title = f"{item.get('code') or item_id} · {item.get('name') or '临床标本'}"
        else:
            row = conn.execute("SELECT * FROM reagents WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise ApiError(404, "试剂不存在")
            item = normalize_reagent_item(row, conn)
            events = _reagent_events(conn, row)
            title = f"{item.get('code') or item_id} · {item.get('name') or '试剂/耗材'}"
    events.sort(key=lambda event: event.get("time") or "", reverse=True)
    return {
        "item": {
            "item_type": clean_type,
            "id": item_id,
            "code": item.get("code"),
            "title": title,
        },
        "items": events,
        "count": len(events),
    }


def _actor(row: Any) -> str:
    return str(row["actor_name"] or row["username"] or "") if "actor_name" in row.keys() else ""


def _sample_events(conn: Any, sample: Any) -> list[dict[str, Any]]:
    item_id = int(sample["id"])
    events = [{
        "time": sample["created_at"],
        "event_type": "sample_created",
        "title": "标本入库",
        "summary": f"登记标本 {sample['code']}，样本号 {sample['name']}，类型 {sample['category'] or '未填写'}。",
        "actor": "",
        "related_table": "clinical_samples",
        "related_id": item_id,
    }]
    if sample["source_code"] and sample["source_code"] != sample["code"]:
        events.append({
            "time": sample["created_at"],
            "event_type": "aliquot",
            "title": "分装生成",
            "summary": f"由 {sample['source_code']} 分装生成，当前管号 {sample['aliquot_no'] or '-'}。",
            "actor": "",
            "related_table": "clinical_samples",
            "related_id": item_id,
        })
    events.extend(_movement_events(conn, "sample", item_id))
    events.extend(_audit_events(conn, "clinical_samples", item_id, "信息修改"))
    return events


def _reagent_events(conn: Any, reagent: Any) -> list[dict[str, Any]]:
    item_id = int(reagent["id"])
    catalog_no = str(reagent["catalog_no"] or "").strip()
    events = [{
        "time": reagent["created_at"],
        "event_type": "reagent_created",
        "title": "试剂入库",
        "summary": f"登记试剂 {reagent['code']}，名称 {reagent['name']}。",
        "actor": "",
        "related_table": "reagents",
        "related_id": item_id,
    }]
    events.extend(_arrival_events(conn, item_id))
    if catalog_no:
        events.extend(_validation_events(conn, catalog_no))
    events.extend(_movement_events(conn, "reagent", item_id))
    events.extend(_audit_events(conn, "reagents", item_id, "信息修改"))
    return events


def _arrival_events(conn: Any, reagent_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.*, u.display_name AS actor_name, u.username
        FROM arrivals a
        LEFT JOIN users u ON u.id = a.received_by
        WHERE a.item_type = 'reagent' AND a.item_id = ?
        ORDER BY a.created_at DESC
        """,
        (reagent_id,),
    ).fetchall()
    return [
        {
            "time": row["created_at"] or row["entry_date"],
            "event_type": "arrival",
            "title": "到货入库",
            "summary": f"到货入库到 {row['location_snapshot'] or '未归位'}。",
            "actor": _actor(row),
            "to_location": row["location_snapshot"],
            "related_table": "arrivals",
            "related_id": row["id"],
        }
        for row in rows
    ]


def _validation_events(conn: Any, catalog_no: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT v.*, u.display_name AS actor_name, u.username
        FROM validations v
        LEFT JOIN users u ON u.id = v.validator_id
        WHERE v.catalog_no = ?
        ORDER BY v.created_at DESC
        """,
        (catalog_no,),
    ).fetchall()
    return [
        {
            "time": row["created_at"] or row["validation_date"],
            "event_type": "validation",
            "title": "货号验证",
            "summary": f"货号 {catalog_no} 在 {row['method'] or '未填写方法'} 中结果为 {row['result'] or '未填写'}。",
            "actor": _actor(row),
            "details": {
                "catalog_no": catalog_no,
                "validation_date": row["validation_date"],
                "method": row["method"],
                "result": row["result"],
                "validator": _actor(row),
                "description": row["description"],
                "image_path": row["image_path"],
                "created_at": row["created_at"],
            },
            "related_table": "validations",
            "related_id": row["id"],
        }
        for row in rows
    ]


def _movement_events(conn: Any, item_type: str, item_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT m.*, u.display_name AS actor_name, u.username
        FROM movements m
        LEFT JOIN users u ON u.id = m.moved_by
        WHERE m.item_type = ? AND m.item_id = ?
        ORDER BY m.moved_at DESC
        """,
        (item_type, item_id),
    ).fetchall()
    events = []
    for row in rows:
        reason = str(row["reason"] or "")
        title = "出库登记" if "出库" in reason or str(row["to_location_snapshot"] or "").startswith("未放置（已耗尽") else "位置移动"
        if reason.startswith("回滚"):
            title = "移动回滚"
        elif row["reverted_by_movement_id"]:
            title = "已被回滚的移动"
        events.append({
            "time": row["moved_at"],
            "event_type": "movement",
            "title": title,
            "summary": f"从 {row['from_location_snapshot'] or '未归位'} 到 {row['to_location_snapshot'] or '未归位'}" + (f"，原因：{reason}" if reason else ""),
            "actor": _actor(row),
            "from_location": row["from_location_snapshot"],
            "to_location": row["to_location_snapshot"],
            "related_table": "movements",
            "related_id": row["id"],
        })
    return events


def _audit_events(conn: Any, table: str, item_id: int, title: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT a.*, u.display_name AS actor_name, u.username
        FROM audit_logs a
        LEFT JOIN users u ON u.id = a.user_id
        WHERE a.target_table = ? AND a.target_id = ?
        ORDER BY a.created_at DESC
        """,
        (table, item_id),
    ).fetchall()
    events = []
    for row in rows:
        action = str(row["action"] or "")
        if "create" in action:
            continue
        events.append({
            "time": row["created_at"],
            "event_type": "audit",
            "title": title,
            "summary": "管理员或维护人员更新了该对象信息。",
            "actor": _actor(row),
            "related_table": "audit_logs",
            "related_id": row["id"],
        })
    return events
