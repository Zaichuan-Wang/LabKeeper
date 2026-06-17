from __future__ import annotations

from typing import Any

from core.common import ApiError, create_audit, now_text, row_dict
from db.database import connect


METADATA_FIELDS = (
    "target",
    "conjugate",
    "react_species",
    "host_species",
    "clone",
    "isotype",
    "aliases",
    "raw_note",
)


def clean_catalog_no(value: Any) -> str:
    catalog_no = str(value or "").strip()
    if not catalog_no:
        raise ApiError(400, "货号不能为空")
    return catalog_no


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _metadata_payload(data: dict[str, Any], *, patch: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in METADATA_FIELDS:
        if field in data:
            payload[field] = _clean_text(data.get(field))
        elif not patch:
            payload[field] = ""
    return payload


def get_metadata(catalog_no: Any) -> dict[str, Any]:
    clean_catalog = clean_catalog_no(catalog_no)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM antibody_metadata WHERE catalog_no = ?",
            (clean_catalog,),
        ).fetchone()
    return {"item": row_dict(row)}


def create_metadata(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    catalog_no = clean_catalog_no(data.get("catalog_no"))
    payload = _metadata_payload(data)
    timestamp = now_text()
    with connect() as conn:
        existing = conn.execute(
            "SELECT catalog_no FROM antibody_metadata WHERE catalog_no = ?",
            (catalog_no,),
        ).fetchone()
        if existing is not None:
            raise ApiError(409, "该货号的抗体元数据已存在")
        conn.execute(
            """
            INSERT INTO antibody_metadata
                (catalog_no, target, conjugate, react_species, host_species, clone, isotype, aliases, raw_note,
                 created_by, updated_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                catalog_no,
                payload["target"],
                payload["conjugate"],
                payload["react_species"],
                payload["host_species"],
                payload["clone"],
                payload["isotype"],
                payload["aliases"],
                payload["raw_note"],
                user["id"],
                user["id"],
                timestamp,
                timestamp,
            ),
        )
        create_audit(conn, user["id"], "api_create_antibody_metadata", "antibody_metadata", None, {"catalog_no": catalog_no, **payload})
        conn.commit()
        row = conn.execute("SELECT * FROM antibody_metadata WHERE catalog_no = ?", (catalog_no,)).fetchone()
    return {"item": row_dict(row)}


def update_metadata(catalog_no: Any, data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    clean_catalog = clean_catalog_no(catalog_no)
    updates = _metadata_payload(data, patch=True)
    if not updates:
        raise ApiError(400, "没有可更新字段")
    updates["updated_by"] = user["id"]
    updates["updated_at"] = now_text()
    with connect() as conn:
        old = conn.execute(
            "SELECT * FROM antibody_metadata WHERE catalog_no = ?",
            (clean_catalog,),
        ).fetchone()
        if old is None:
            raise ApiError(404, "该货号的抗体元数据不存在")
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE antibody_metadata SET {assignments} WHERE catalog_no = ?",
            list(updates.values()) + [clean_catalog],
        )
        current = conn.execute(
            "SELECT * FROM antibody_metadata WHERE catalog_no = ?",
            (clean_catalog,),
        ).fetchone()
        create_audit(
            conn,
            user["id"],
            "api_update_antibody_metadata",
            "antibody_metadata",
            None,
            row_dict(current),
            row_dict(old),
        )
        conn.commit()
    return {"item": row_dict(current)}
