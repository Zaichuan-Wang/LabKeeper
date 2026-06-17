from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "backend" / "db" / "schema.sql"
DEFAULT_INPUT = ROOT / "-80js.txt"
DEFAULT_DB = ROOT / "outputs" / "80js_lab_inventory.sqlite3"

IMPORT_MARKER = "[80js-import]"
DEFAULT_IMPORT_ROOT_NAME = "-80js 导入"
DEFAULT_SAMPLE_PREFIX = "SP"
SAMPLE_CODE_WIDTH = 6

STATUS_AVAILABLE = "可用"
SYSTEM_STORAGE_NODES = (
    (-1, "未订购", -100),
    (-2, "未到货", -99),
    (-3, "未归位", -98),
    (-4, "已出库", -97),
)

LOCATION_RE = re.compile(
    r"^\s*(?P<freezer>\d+\s*号(?:冰箱)?)?\s*"
    r"(?P<section>[上下])?(?:层)?\s*"
    r"第\s*(?P<column>\d+)\s*列\s*"
    r"[（(]\s*(?P<rack>\d+)\s*[，,]\s*(?P<slot>[A-Za-z])\s*[)）]\s*$"
)
WELL_RE = re.compile(r"^\s*(?P<row>[A-Za-z]+)\s*(?P<col>\d+)\s*$")
AMOUNT_RE = re.compile(r"^\s*(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(?P<unit>.*)\s*$")


def main() -> None:
    args = parse_args()
    input_path = args.input.resolve()
    db_path = args.db.resolve()
    boxes = load_boxes(input_path)
    box_rows, rows = build_import_data(boxes, input_path.name, args.default_entry_date)
    if args.dry_run:
        print_summary("Dry run", db_path, rows, boxes, replaced=0, storage_nodes=0)
        return

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        now = now_text()
        ensure_system_storage_nodes(conn, now)
        root_id = ensure_root_storage_node(conn, now)
        if args.mode == "replace":
            replaced = delete_previous_import(conn)
        else:
            replaced = 0
        import_root_id = get_or_create_storage_node(
            conn,
            parent_id=root_id,
            name=args.import_root_name,
            space_type=5,
            location_code=args.import_root_name,
            note=f"{IMPORT_MARKER} {input_path.name}",
            sort_order=9000,
            timestamp=now,
            user_id=args.user_id,
        )
        code_number = next_sample_number(conn, args.sample_prefix)
        source_counters = existing_source_aliquot_counts(conn)
        storage_cache: dict[tuple[int | None, str], int] = {}
        storage_nodes_created = 0
        box_node_ids: dict[str, int] = {}
        for box_row in box_rows:
            box_node_id, created = ensure_box_node(
                conn,
                import_root_id=import_root_id,
                row=box_row,
                timestamp=now,
                user_id=args.user_id,
                cache=storage_cache,
            )
            storage_nodes_created += created
            box_node_ids[box_key(box_row)] = box_node_id
        for row in rows:
            box_node_id = box_node_ids[box_key(row)]
            source_code = row["source_code"]
            source_counters[source_code] += 1
            code = f"{args.sample_prefix}{code_number:0{SAMPLE_CODE_WIDTH}d}"
            code_number += 1
            insert_sample(
                conn,
                row=row,
                code=code,
                source_code=source_code,
                aliquot_no=source_counters[source_code],
                box_node_id=box_node_id,
                timestamp=now,
                user_id=args.user_id,
            )
        conn.commit()

    print_summary("Imported", db_path, rows, boxes, replaced=replaced, storage_nodes=storage_nodes_created)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import -80js.txt freezer-box records into LabKeeper clinical_samples."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Path to -80js.txt")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help="Target SQLite database. Defaults to outputs/80js_lab_inventory.sqlite3",
    )
    parser.add_argument(
        "--mode",
        choices=("replace", "append"),
        default="replace",
        help="replace deletes previous rows whose note starts with [80js-import]; append keeps them.",
    )
    parser.add_argument("--import-root-name", default=DEFAULT_IMPORT_ROOT_NAME, help="Root storage node name.")
    parser.add_argument("--sample-prefix", default=DEFAULT_SAMPLE_PREFIX, help="System sample code prefix.")
    parser.add_argument(
        "--default-entry-date",
        default=date.today().isoformat(),
        help="Entry date used when the source well has no date.",
    )
    parser.add_argument("--user-id", type=int, default=None, help="Optional created_by/updated_by user id.")
    parser.add_argument("--dry-run", action="store_true", help="Read and summarize without writing the database.")
    return parser.parse_args()


def load_boxes(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Input file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Input is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, list):
        raise SystemExit("Input JSON must be a list of freezer boxes.")
    return [box for box in data if isinstance(box, dict)]


def build_import_data(
    boxes: list[dict[str, Any]],
    source_file: str,
    default_entry_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sample_types: dict[str, set[str]] = defaultdict(set)
    raw_rows: list[dict[str, Any]] = []
    box_rows: list[dict[str, Any]] = []
    for box_index, box in enumerate(boxes, start=1):
        wells = box.get("wells") or {}
        if not isinstance(wells, dict):
            wells = {}
        box_row = base_box_row(box, box_index)
        box_rows.append(box_row)
        for well_name in sorted(wells, key=well_sort_key):
            well = wells.get(well_name) or {}
            if not isinstance(well, dict):
                continue
            if not well_has_content(well):
                continue
            sample_name = clean_text(well.get("sample"))
            sample_type = clean_text(well.get("type")) or "临床标本"
            if sample_name:
                sample_types[sample_name].add(sample_type)
            amount_value, amount_unit, raw_amount = parse_amount(well.get("amount"))
            well_row, well_col = parse_well(well_name)
            entry_date = clean_text(well.get("date")) or default_entry_date
            raw_rows.append(
                {
                    **box_row,
                    "source_file": source_file,
                    "well": clean_text(well_name),
                    "well_row": well_row,
                    "well_col": well_col,
                    "sample_name": sample_name or "未命名样本",
                    "sample_type": sample_type,
                    "passage": clean_text(well.get("passage")),
                    "amount": amount_value,
                    "amount_unit": amount_unit,
                    "raw_amount": raw_amount,
                    "entry_date": entry_date,
                    "source_date": clean_text(well.get("date")),
                    "well_note": clean_text(well.get("note")),
                }
            )

    source_seen: dict[str, int] = defaultdict(int)
    for row in raw_rows:
        sample_name = row["sample_name"]
        sample_type = row["sample_type"]
        if sample_name == "未命名样本":
            base_source = f"80JS:{row['source_box_id'] or row['box_name']}:{row['well']}"
        elif len(sample_types.get(sample_name, set())) > 1:
            base_source = f"{sample_name} | {sample_type}"
        else:
            base_source = sample_name
        row["source_code"] = base_source
        source_seen[base_source] += 1
    return box_rows, raw_rows


def base_box_row(box: dict[str, Any], box_index: int) -> dict[str, Any]:
    location = clean_text(box.get("location"))
    return {
        "source_box_id": clean_text(box.get("id")),
        "box_index": box_index,
        "box_name": clean_text(box.get("name")) or f"Box {box_index}",
        "box_location": location,
        "box_desc": clean_text(box.get("desc")),
        "box_rows": positive_int(box.get("rows"), 9),
        "box_cols": positive_int(box.get("cols"), 9),
        **parse_location(location),
    }


def box_key(row: dict[str, Any]) -> str:
    return row["source_box_id"] or f"box-index:{row['box_index']}"


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def well_has_content(well: dict[str, Any]) -> bool:
    return any(clean_text(well.get(key)) for key in ("sample", "type", "passage", "amount", "date", "note"))


def positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def parse_well(value: str) -> tuple[str, int | None]:
    match = WELL_RE.match(value)
    if not match:
        return clean_text(value), None
    return match.group("row").upper(), int(match.group("col"))


def well_sort_key(value: str) -> tuple[int, int, str]:
    row, col = parse_well(str(value))
    row_number = 0
    for char in row:
        if not char.isalpha():
            continue
        row_number = row_number * 26 + (ord(char.upper()) - ord("A") + 1)
    return (row_number or 999, col or 999, str(value))


def parse_amount(value: Any) -> tuple[float | None, str, str]:
    raw = clean_text(value)
    if not raw:
        return None, "", ""
    match = AMOUNT_RE.match(raw)
    if not match:
        return None, "", raw
    try:
        amount = float(match.group("number"))
    except ValueError:
        return None, "", raw
    return amount, match.group("unit").strip(), raw


def parse_location(location: str) -> dict[str, Any]:
    match = LOCATION_RE.match(location)
    if not match:
        return {
            "location_parse_ok": 0,
            "freezer_name": location,
            "freezer_layer": "",
            "rack_column": None,
            "rack_index": None,
            "box_slot": "",
            "location_path": location,
        }
    freezer = normalize_freezer_name(match.group("freezer"))
    layer = {"上": "上层", "下": "下层"}.get(match.group("section") or "", "")
    rack_column = int(match.group("column"))
    rack_index = int(match.group("rack"))
    box_slot = match.group("slot").upper()
    levels = [freezer, layer, f"第{rack_column}列", f"第{rack_index}位", f"{box_slot}位"]
    return {
        "location_parse_ok": 1,
        "freezer_name": freezer,
        "freezer_layer": layer,
        "rack_column": rack_column,
        "rack_index": rack_index,
        "box_slot": box_slot,
        "location_path": " / ".join(level for level in levels if level),
    }


def normalize_freezer_name(value: str | None) -> str:
    text = clean_text(value)
    if not text:
        return "-80 冰箱"
    text = re.sub(r"\s+", "", text)
    return text if "冰箱" in text else f"{text}冰箱"


def ensure_schema(conn: sqlite3.Connection) -> None:
    if not SCHEMA_PATH.exists():
        raise SystemExit(f"Schema file not found: {SCHEMA_PATH}")
    existing = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('clinical_samples', 'storage_nodes')"
        ).fetchall()
    }
    if {"clinical_samples", "storage_nodes"}.issubset(existing):
        return
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def ensure_system_storage_nodes(conn: sqlite3.Connection, timestamp: str) -> None:
    for node_id, label, sort_order in SYSTEM_STORAGE_NODES:
        conn.execute(
            """
            INSERT INTO storage_nodes
                (id, parent_id, name, node_type, space_type, location_code, rows, cols, grid_row, grid_col,
                 note, sort_order, created_by, updated_by, created_at, updated_at)
            VALUES (?, NULL, ?, 'system', 5, ?, NULL, NULL, NULL, NULL, '系统状态节点', ?, NULL, NULL, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                node_type = 'system',
                location_code = excluded.location_code,
                note = excluded.note,
                sort_order = excluded.sort_order,
                updated_at = excluded.updated_at
            """,
            (node_id, label, label, sort_order, timestamp, timestamp),
        )


def ensure_root_storage_node(conn: sqlite3.Connection, timestamp: str) -> int:
    row = conn.execute(
        """
        SELECT id FROM storage_nodes
        WHERE parent_id IS NULL AND id > 0 AND COALESCE(node_type, 'space') != 'system'
        ORDER BY id LIMIT 1
        """
    ).fetchone()
    if row is not None:
        return int(row["id"])
    conn.execute(
        """
        INSERT INTO storage_nodes
            (id, parent_id, name, node_type, space_type, location_code, rows, cols, grid_row, grid_col, note, sort_order,
             created_by, updated_by, created_at, updated_at)
        VALUES (1, NULL, '研究所', 'space', 5, '研究所', NULL, NULL, NULL, NULL, '默认根节点', 0, NULL, NULL, ?, ?)
        """,
        (timestamp, timestamp),
    )
    return 1


def delete_previous_import(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "DELETE FROM clinical_samples WHERE note LIKE ?",
        (f"{IMPORT_MARKER}%",),
    )
    return int(cursor.rowcount or 0)


def get_or_create_storage_node(
    conn: sqlite3.Connection,
    *,
    parent_id: int | None,
    name: str,
    space_type: int,
    location_code: str | None = None,
    rows: int | None = None,
    cols: int | None = None,
    note: str | None = None,
    sort_order: int = 0,
    timestamp: str,
    user_id: int | None,
) -> int:
    row = conn.execute(
        """
        SELECT id FROM storage_nodes
        WHERE parent_id IS ? AND name = ? AND COALESCE(node_type, 'space') != 'system'
        LIMIT 1
        """,
        (parent_id, name),
    ).fetchone()
    if row is not None:
        node_id = int(row["id"])
        conn.execute(
            """
            UPDATE storage_nodes
            SET space_type = ?, location_code = COALESCE(?, location_code), rows = COALESCE(?, rows),
                cols = COALESCE(?, cols), note = COALESCE(?, note), updated_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (space_type, location_code, rows, cols, note, user_id, timestamp, node_id),
        )
        return node_id
    cur = conn.execute(
        """
        INSERT INTO storage_nodes
            (parent_id, name, node_type, space_type, location_code, rows, cols, grid_row, grid_col,
             note, sort_order, created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, 'space', ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?)
        """,
        (parent_id, name, space_type, location_code, rows, cols, note, sort_order, user_id, user_id, timestamp, timestamp),
    )
    return int(cur.lastrowid)


def ensure_box_node(
    conn: sqlite3.Connection,
    *,
    import_root_id: int,
    row: dict[str, Any],
    timestamp: str,
    user_id: int | None,
    cache: dict[tuple[int | None, str], int],
) -> tuple[int, int]:
    created = 0
    parent_id = import_root_id
    levels = [
        (row["freezer_name"] or "-80 冰箱", 2),
        (row["freezer_layer"], 5),
        (f"第{row['rack_column']}列" if row["rack_column"] else "", 4),
        (f"第{row['rack_index']}位" if row["rack_index"] else "", 4),
        (f"{row['box_slot']}位" if row["box_slot"] else "", 4),
    ]
    if not row["location_parse_ok"] and row["box_location"]:
        levels = [(row["box_location"], 5)]
    for name, space_type in levels:
        if not name:
            continue
        key = (parent_id, name)
        if key in cache:
            parent_id = cache[key]
            continue
        before = existing_storage_node_id(conn, parent_id, name)
        parent_id = get_or_create_storage_node(
            conn,
            parent_id=parent_id,
            name=name,
            space_type=space_type,
            location_code=name,
            note=f"{IMPORT_MARKER} 位置层级",
            timestamp=timestamp,
            user_id=user_id,
        )
        cache[key] = parent_id
        if before is None:
            created += 1

    box_name = row["box_name"]
    key = (parent_id, box_name)
    if key in cache:
        return cache[key], created
    before = existing_storage_node_id(conn, parent_id, box_name)
    box_node_id = get_or_create_storage_node(
        conn,
        parent_id=parent_id,
        name=box_name,
        space_type=1,
        location_code=row["source_box_id"] or box_name,
        rows=row["box_rows"],
        cols=row["box_cols"],
        note=box_note(row),
        sort_order=row["box_index"],
        timestamp=timestamp,
        user_id=user_id,
    )
    cache[key] = box_node_id
    if before is None:
        created += 1
    return box_node_id, created


def existing_storage_node_id(conn: sqlite3.Connection, parent_id: int | None, name: str) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM storage_nodes
        WHERE parent_id IS ? AND name = ? AND COALESCE(node_type, 'space') != 'system'
        LIMIT 1
        """,
        (parent_id, name),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def box_note(row: dict[str, Any]) -> str:
    parts = [
        IMPORT_MARKER,
        f"旧盒ID: {row['source_box_id']}" if row["source_box_id"] else "",
        f"原位置: {row['box_location']}" if row["box_location"] else "",
        f"解析路径: {row['location_path']}" if row["location_path"] else "",
        f"盒描述: {row['box_desc']}" if row["box_desc"] else "",
    ]
    return "；".join(part for part in parts if part)


def insert_sample(
    conn: sqlite3.Connection,
    *,
    row: dict[str, Any],
    code: str,
    source_code: str,
    aliquot_no: int,
    box_node_id: int,
    timestamp: str,
    user_id: int | None,
) -> None:
    note = sample_note(row)
    conn.execute(
        """
        INSERT INTO clinical_samples
            (code, source_code, aliquot_no, name, category, amount, amount_unit, quantity, status,
             storage_node_id, grid_cell, entry_date, note, created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            code,
            source_code,
            aliquot_no,
            row["sample_name"],
            row["sample_type"],
            row["amount"],
            row["amount_unit"],
            STATUS_AVAILABLE,
            box_node_id,
            row["well"],
            row["entry_date"],
            note,
            user_id,
            user_id,
            timestamp,
            timestamp,
        ),
    )


def sample_note(row: dict[str, Any]) -> str:
    parts = [
        IMPORT_MARKER,
        f"来源文件: {row['source_file']}",
        f"盒: {row['box_name']}",
        f"旧盒ID: {row['source_box_id']}" if row["source_box_id"] else "",
        f"原位置: {row['box_location']}" if row["box_location"] else "",
        f"解析路径: {row['location_path']}" if row["location_path"] else "",
        f"孔位: {row['well']}",
        f"passage: {row['passage']}" if row["passage"] else "",
        f"旧日期: {row['source_date']}" if row["source_date"] else "",
        f"旧数量: {row['raw_amount']}" if row["raw_amount"] and row["amount"] is None else "",
        f"原备注: {row['well_note']}" if row["well_note"] else "",
    ]
    return "；".join(part for part in parts if part)


def next_sample_number(conn: sqlite3.Connection, prefix: str) -> int:
    rows = conn.execute("SELECT code FROM clinical_samples WHERE code LIKE ?", (f"{prefix}%",)).fetchall()
    max_number = 0
    for row in rows:
        code = clean_text(row["code"])
        if not code.startswith(prefix):
            continue
        suffix = code[len(prefix):]
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    return max_number + 1


def existing_source_aliquot_counts(conn: sqlite3.Connection) -> defaultdict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    rows = conn.execute(
        """
        SELECT COALESCE(source_code, code) AS source, MAX(COALESCE(aliquot_no, 0)) AS n
        FROM clinical_samples
        GROUP BY COALESCE(source_code, code)
        """
    ).fetchall()
    for row in rows:
        source = clean_text(row["source"])
        if source:
            counts[source] = int(row["n"] or 0)
    return counts


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def print_summary(
    action: str,
    db_path: Path,
    rows: list[dict[str, Any]],
    boxes: list[dict[str, Any]],
    *,
    replaced: int,
    storage_nodes: int,
) -> None:
    unmatched_locations = sorted({row["box_location"] for row in rows if not row["location_parse_ok"] and row["box_location"]})
    print(f"{action}: {len(rows)} samples from {len(boxes)} boxes")
    print(f"Database: {db_path}")
    print(f"Previous imported samples deleted: {replaced}")
    print(f"Storage nodes created: {storage_nodes}")
    print(f"Unparsed locations: {len(unmatched_locations)}")
    for location in unmatched_locations[:10]:
        print(f"  - {location}")


if __name__ == "__main__":
    main()
