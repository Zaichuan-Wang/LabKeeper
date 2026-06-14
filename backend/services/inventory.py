from __future__ import annotations

import sqlite3
import math
from typing import Any

from core.common import ApiError, clean_int_range
from core.constants import PHYSICAL_INVENTORY_STATUS_SQL
from db.database import connect
from services.storage_inventory import (
    attach_aliquot_totals,
    batch_node_paths_and_descendants,
    descendant_node_ids,
    normalize_reagent_item,
    normalize_sample_item,
)
from services import clinical_samples
from services import reagents


REAGENT_PAYLOAD_KEYS = (
    "code", "source_code", "name", "category", "brand", "catalog_no", "amount", "amount_unit",
    "quantity", "status", "entry_date", "expiration_date", "validation_status",
    "storage_node_id", "position_in_box", "separate_items", "note",
)
SAMPLE_PAYLOAD_KEYS = (
    "code", "source_code", "name", "category", "tube_count", "amount", "amount_unit",
    "quantity", "status", "entry_date", "expiration_date", "validation_status",
    "storage_node_id", "position_in_box", "separate_items", "note",
)


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
    for key in REAGENT_PAYLOAD_KEYS:
        _copy_present(data, key, payload)
    return payload


def sample_payload(data: dict[str, Any]) -> dict[str, Any]:
    if str(data.get("brand") or "").strip() or str(data.get("catalog_no") or "").strip():
        raise ApiError(400, "临床标本不填写品牌或货号")
    payload: dict[str, Any] = {}
    for key in SAMPLE_PAYLOAD_KEYS:
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
    return clean_int_range(value, 80, 1, 500)


def _clean_page(value: str) -> int:
    return clean_int_range(value, 1, 1, 1_000_000)


def _pagination(query: dict[str, list[str]]) -> tuple[int, int, int]:
    page_size = _clean_limit(_query_value(query, "page_size") or _query_value(query, "limit", "80"))
    page = _clean_page(_query_value(query, "page", "1"))
    offset = clean_int_range(_query_value(query, "offset", ""), (page - 1) * page_size, 0, 1_000_000)
    return page, page_size, offset


def _append_keyword_clause(
    conn: sqlite3.Connection,
    item_type: str,
    keyword: str,
    like_fields: list[str],
    path_cache: dict[int, str],
    desc_cache: dict[int, list[int]],
    clauses: list[str],
    params: list[Any],
) -> None:
    if not keyword:
        return
    keyword_nodes = _keyword_node_ids(conn, keyword, path_cache, desc_cache)
    node_clause = ""
    if keyword_nodes:
        placeholders = ",".join("?" for _ in keyword_nodes)
        node_clause = f" OR storage_node_id IN ({placeholders})"
    like = f"%{keyword}%"
    field_clause = " OR ".join(f"{field} LIKE ?" for field in like_fields)
    clauses.append(f"({field_clause}{node_clause})")
    params.extend([like] * len(like_fields))
    params.extend(keyword_nodes)


def _storage_clause(
    conn: sqlite3.Connection,
    query: dict[str, list[str]],
    clauses: list[str],
    params: list[Any],
    desc_cache: dict[int, list[int]] | None = None,
) -> None:
    storage_node_id = clean_int_range(_query_value(query, "storage_node_id", "0"), 0, 0, 1_000_000)
    if not storage_node_id:
        return
    include_descendants = _query_value(query, "include_descendants", "1") != "0"
    if include_descendants and desc_cache is not None:
        node_ids = desc_cache.get(storage_node_id, [storage_node_id])
    else:
        node_ids = descendant_node_ids(conn, storage_node_id, True) if include_descendants else [storage_node_id]
    placeholders = ",".join("?" for _ in node_ids)
    clauses.append(f"storage_node_id IN ({placeholders})")
    params.extend(node_ids)


def _keyword_node_ids(
    conn: sqlite3.Connection,
    keyword: str,
    path_cache: dict[int, str],
    desc_cache: dict[int, list[int]],
) -> list[int]:
    if not keyword:
        return []
    lowered = keyword.lower()
    ids: set[int] = set()
    rows = conn.execute("SELECT id, name, location_code, node_type, note FROM storage_nodes ORDER BY id LIMIT 1000").fetchall()
    for row in rows:
        node_id = int(row["id"])
        path = path_cache.get(node_id, "")
        haystack = " ".join(str(value or "") for value in (row["name"], row["location_code"], row["node_type"], row["note"], path)).lower()
        if lowered in haystack:
            ids.update(desc_cache.get(node_id, [node_id]))
    return sorted(ids)


def _search_reagents(
    conn: sqlite3.Connection,
    query: dict[str, list[str]],
    keyword: str,
    available_only: bool,
    limit: int,
    offset: int,
    path_cache: dict[int, str],
    desc_cache: dict[int, list[int]],
) -> tuple[list[dict[str, Any]], int]:
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
        clauses.append(f"COALESCE(status, '') IN {PHYSICAL_INVENTORY_STATUS_SQL}")
    _append_keyword_clause(
        conn,
        "reagent",
        keyword,
        ["name", "code", "source_code", "catalog_no", "brand", "category", "amount", "amount_unit", "note", "position_in_box"],
        path_cache,
        desc_cache,
        clauses,
        params,
    )
    validation_status = _query_value(query, "validation_status")
    if validation_status:
        clauses.append("validation_status = ?")
        params.append(validation_status)
    _storage_clause(conn, query, clauses, params, desc_cache)
    sql = "SELECT * FROM reagents"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    total = int(conn.execute(sql.replace("SELECT *", "SELECT COUNT(*) AS n", 1), params).fetchone()["n"] or 0)
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?"
    rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    items = attach_aliquot_totals(conn, [normalize_reagent_item(row, conn, path_cache) for row in rows])
    return [_with_display_fields(item) for item in items], total


def _search_samples(
    conn: sqlite3.Connection,
    query: dict[str, list[str]],
    keyword: str,
    available_only: bool,
    limit: int,
    offset: int,
    path_cache: dict[int, str],
    desc_cache: dict[int, list[int]],
) -> tuple[list[dict[str, Any]], int]:
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
        clauses.append(f"status IN {PHYSICAL_INVENTORY_STATUS_SQL}")
    _append_keyword_clause(
        conn,
        "sample",
        keyword,
        ["code", "name", "category", "amount", "amount_unit", "note", "position_in_box"],
        path_cache,
        desc_cache,
        clauses,
        params,
    )
    _storage_clause(conn, query, clauses, params, desc_cache)
    sql = "SELECT * FROM clinical_samples"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    total = int(conn.execute(sql.replace("SELECT *", "SELECT COUNT(*) AS n", 1), params).fetchone()["n"] or 0)
    sql += " ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?"
    rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    items = attach_aliquot_totals(conn, [normalize_sample_item(row, conn, path_cache) for row in rows])
    return [_with_display_fields(item) for item in items], total


def _search_spaces(conn: sqlite3.Connection, keyword: str, limit: int, offset: int, path_cache: dict[int, str]) -> tuple[list[dict[str, Any]], int]:
    params: list[Any] = []
    where = ""
    if keyword:
        like = f"%{keyword}%"
        where = "WHERE name LIKE ? OR location_code LIKE ? OR node_type LIKE ? OR note LIKE ?"
        params.extend([like] * 4)
    if not keyword:
        total = int(conn.execute(f"SELECT COUNT(*) AS n FROM storage_nodes {where}", params).fetchone()["n"] or 0)
    else:
        total = 0
    rows = conn.execute(
        f"SELECT * FROM storage_nodes {where} ORDER BY sort_order, id LIMIT ?",
        [*params, 1000 if keyword else limit + offset],
    ).fetchall()
    lowered = keyword.lower()
    items: list[dict[str, Any]] = []
    for row in rows:
        path = path_cache.get(int(row["id"]), "")
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
            "display_subtitle": "普通空间",
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
    if keyword:
        total = len(items)
    return items[offset:offset + limit], total


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
    page, page_size, offset = _pagination(query)
    with connect() as conn:
        path_cache, desc_cache = batch_node_paths_and_descendants(conn)
        items: list[dict[str, Any]] = []
        total = 0
        if item_type in {"reagent", "all"}:
            fetch_offset = 0 if item_type == "all" else offset
            fetch_limit = offset + page_size if item_type == "all" else page_size
            reagent_items, reagent_total = _search_reagents(conn, query, keyword, available_only, fetch_limit, fetch_offset, path_cache, desc_cache)
            items.extend(reagent_items)
            total += reagent_total
        if item_type in {"sample", "all"}:
            fetch_offset = 0 if item_type == "all" else offset
            fetch_limit = offset + page_size if item_type == "all" else page_size
            sample_items, sample_total = _search_samples(conn, query, keyword, available_only, fetch_limit, fetch_offset, path_cache, desc_cache)
            items.extend(sample_items)
            total += sample_total
        if not available_only and item_type in {"space", "all"}:
            fetch_offset = 0 if item_type == "all" else offset
            fetch_limit = offset + page_size if item_type == "all" else page_size
            space_items, space_total = _search_spaces(conn, keyword, fetch_limit, fetch_offset, path_cache)
            items.extend(space_items)
            total += space_total
    items.sort(key=lambda item: (str(item.get("updated_at") or ""), int(item.get("id") or 0)), reverse=True)
    if item_type == "all":
        items = items[offset:offset + page_size]
    return {
        "items": items,
        "count": len(items),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)) if page_size else 1,
    }


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


def _timeline_event(
    *,
    time: Any,
    event_type: str,
    title: str,
    summary: str,
    actor: str = "",
    related_table: str,
    related_id: Any,
    **extra: Any,
) -> dict[str, Any]:
    event = {
        "time": time,
        "event_type": event_type,
        "title": title,
        "summary": summary,
        "actor": actor,
        "related_table": related_table,
        "related_id": related_id,
    }
    event.update(extra)
    return event


def _sample_events(conn: Any, sample: Any) -> list[dict[str, Any]]:
    item_id = int(sample["id"])
    events = [_timeline_event(
        time=sample["created_at"],
        event_type="sample_created",
        title="标本入库",
        summary=f"登记标本 {sample['code']}，样本号 {sample['name']}，类型 {sample['category'] or '未填写'}。",
        related_table="clinical_samples",
        related_id=item_id,
    )]
    if sample["source_code"] and sample["source_code"] != sample["code"]:
        events.append(_timeline_event(
            time=sample["created_at"],
            event_type="aliquot",
            title="分装生成",
            summary=f"由 {sample['source_code']} 分装生成，当前管号 {sample['aliquot_no'] or '-'}。",
            related_table="clinical_samples",
            related_id=item_id,
        ))
    events.extend(_movement_events(conn, "sample", item_id))
    events.extend(_audit_events(conn, "clinical_samples", item_id, "信息修改"))
    return events


def _reagent_events(conn: Any, reagent: Any) -> list[dict[str, Any]]:
    item_id = int(reagent["id"])
    catalog_no = str(reagent["catalog_no"] or "").strip()
    events = [_timeline_event(
        time=reagent["created_at"],
        event_type="reagent_created",
        title="试剂入库",
        summary=f"登记试剂 {reagent['code']}，名称 {reagent['name']}。",
        related_table="reagents",
        related_id=item_id,
    )]
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
        _timeline_event(
            time=row["created_at"] or row["entry_date"],
            event_type="arrival",
            title="到货入库",
            summary=f"到货入库到 {row['location_snapshot'] or '未归位'}。",
            actor=_actor(row),
            related_table="arrivals",
            related_id=row["id"],
            to_location=row["location_snapshot"],
        )
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
        _timeline_event(
            time=row["created_at"] or row["validation_date"],
            event_type="validation",
            title="货号验证",
            summary=f"货号 {catalog_no} 在 {row['method'] or '未填写方法'} 中结果为 {row['result'] or '未填写'}。",
            actor=_actor(row),
            related_table="validations",
            related_id=row["id"],
            details={
                "catalog_no": catalog_no,
                "validation_date": row["validation_date"],
                "method": row["method"],
                "result": row["result"],
                "validator": _actor(row),
                "description": row["description"],
                "image_path": row["image_path"],
                "created_at": row["created_at"],
            },
        )
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
        events.append(_timeline_event(
            time=row["moved_at"],
            event_type="movement",
            title=title,
            summary=f"从 {row['from_location_snapshot'] or '未归位'} 到 {row['to_location_snapshot'] or '未归位'}" + (f"，原因：{reason}" if reason else ""),
            actor=_actor(row),
            related_table="movements",
            related_id=row["id"],
            from_location=row["from_location_snapshot"],
            to_location=row["to_location_snapshot"],
        ))
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
        events.append(_timeline_event(
            time=row["created_at"],
            event_type="audit",
            title=title,
            summary="管理员或维护人员更新了该对象信息。",
            actor=_actor(row),
            related_table="audit_logs",
            related_id=row["id"],
        ))
    return events
