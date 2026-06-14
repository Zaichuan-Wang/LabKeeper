from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.common import ApiError, clean_int_range, create_audit, get_logger, now_text
from core.config import BACKUP_SETTINGS_PATH, DB_PATH
from db.database import connect

logger = get_logger("lab.backup")


BACKUP_DIR = DB_PATH.parent / "backups"
BACKUP_NAME_RE = re.compile(r"^lab_inventory[A-Za-z0-9_.-]*\.sqlite3$")
BACKUP_PARTS_RE = re.compile(r"^lab_inventory_(?P<reason>[A-Za-z0-9_.-]+)_\d{8}_\d{6}\.sqlite3$")
COUNT_TABLES = ("users", "storage_nodes", "reagents", "clinical_samples", "orders", "arrivals", "validations", "movements")
DEFAULT_SETTINGS = {
    "enabled": False,
    "interval_hours": 24,
    "retention_days": 30,
    "cleanup_on_schedule": True,
    "last_run_at": "",
    "last_success_at": "",
    "last_error": "",
    "next_run_at": "",
}

_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
_scheduler_lock = threading.Lock()


def _reason_slug(reason: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(reason or "manual").strip()).strip("._-")
    return text[:48] or "manual"


def _backup_path(filename: str) -> Path:
    if not BACKUP_NAME_RE.match(filename):
        raise ApiError(400, "备份文件名不正确")
    path = (BACKUP_DIR / filename).resolve()
    if path.parent != BACKUP_DIR.resolve():
        raise ApiError(400, "备份文件名不正确")
    if not path.exists():
        raise ApiError(404, "备份文件不存在")
    return path


def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in COUNT_TABLES:
        try:
            counts[table] = int(conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"])
        except sqlite3.Error:
            counts[table] = 0
    return counts


def _time_from_text(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _time_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def verify_database_backup(path: str | Path) -> dict[str, Any]:
    backup_path = Path(path)
    conn = sqlite3.connect(backup_path)
    conn.row_factory = sqlite3.Row
    try:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        counts = _table_counts(conn)
    finally:
        conn.close()
    return {"integrity_check": integrity, "table_counts": counts}


def create_database_backup(reason: str = "manual", user: dict[str, Any] | None = None) -> dict[str, Any]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    created_at = now_text()
    stamp = created_at.replace("-", "").replace(":", "").replace(" ", "_")
    filename = f"lab_inventory_{_reason_slug(reason)}_{stamp}.sqlite3"
    target = BACKUP_DIR / filename
    source = sqlite3.connect(DB_PATH)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    verification = verify_database_backup(target)
    item = {
        "path": str(target),
        "filename": filename,
        "reason": reason or "manual",
        "size": target.stat().st_size,
        "created_at": created_at,
        **verification,
    }
    if user:
        with connect() as conn:
            create_audit(conn, user.get("id"), "api_create_database_backup", "database_backups", None, item)
            conn.commit()
    return item


def list_database_backups(limit: int = 50) -> dict[str, Any]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(BACKUP_DIR.glob("lab_inventory*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not BACKUP_NAME_RE.match(path.name):
            continue
        match = BACKUP_PARTS_RE.match(path.name)
        reason = match.group("reason") if match else "manual"
        verification = verify_database_backup(path)
        items.append({
            "filename": path.name,
            "path": str(path),
            "reason": reason,
            "size": path.stat().st_size,
            "created_at": now_text_from_timestamp(path.stat().st_mtime),
            "integrity_check": verification["integrity_check"],
        })
        if len(items) >= limit:
            break
    return {"items": items, "count": len(items), "settings": load_backup_settings()}


def now_text_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def backup_file(filename: str) -> tuple[bytes, str, str]:
    path = _backup_path(filename)
    return path.read_bytes(), "application/x-sqlite3", path.name


def delete_database_backup(filename: str, user: dict[str, Any] | None = None) -> dict[str, Any]:
    path = _backup_path(filename)
    item = {
        "filename": path.name,
        "path": str(path),
        "size": path.stat().st_size,
        "created_at": now_text_from_timestamp(path.stat().st_mtime),
    }
    path.unlink()
    if user:
        with connect() as conn:
            create_audit(conn, user.get("id"), "api_delete_database_backup", "database_backups", None, item)
            conn.commit()
    return {"item": item}


def cleanup_expired_backups(days: int, user: dict[str, Any] | None = None) -> dict[str, Any]:
    keep_days = clean_int_range(days, 30, 1, 3650)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - keep_days * 24 * 60 * 60
    deleted = []
    for path in sorted(BACKUP_DIR.glob("lab_inventory*.sqlite3"), key=lambda p: p.stat().st_mtime):
        if not BACKUP_NAME_RE.match(path.name):
            continue
        if path.stat().st_mtime >= cutoff:
            continue
        item = {
            "filename": path.name,
            "path": str(path),
            "size": path.stat().st_size,
            "created_at": now_text_from_timestamp(path.stat().st_mtime),
        }
        path.unlink()
        deleted.append(item)
    result = {"days": keep_days, "items": deleted, "count": len(deleted)}
    if user:
        with connect() as conn:
            create_audit(conn, user.get("id"), "api_cleanup_database_backups", "database_backups", None, result)
            conn.commit()
    return result


def load_backup_settings() -> dict[str, Any]:
    settings = DEFAULT_SETTINGS.copy()
    if BACKUP_SETTINGS_PATH.exists():
        try:
            raw = json.loads(BACKUP_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                settings.update(raw)
        except json.JSONDecodeError:
            pass
    settings["enabled"] = bool(settings.get("enabled"))
    settings["interval_hours"] = clean_int_range(settings.get("interval_hours"), 24, 1, 720)
    settings["retention_days"] = clean_int_range(settings.get("retention_days"), 30, 1, 3650)
    settings["cleanup_on_schedule"] = bool(settings.get("cleanup_on_schedule", True))
    for key in ("last_run_at", "last_success_at", "last_error", "next_run_at"):
        settings[key] = str(settings.get(key) or "")
    return settings


def save_backup_settings(data: dict[str, Any], user: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = load_backup_settings()
    settings = {
        **previous,
        "enabled": bool(data.get("enabled", previous["enabled"])),
        "interval_hours": clean_int_range(data.get("interval_hours", previous["interval_hours"]), previous["interval_hours"], 1, 720),
        "retention_days": clean_int_range(data.get("retention_days", previous["retention_days"]), previous["retention_days"], 1, 3650),
        "cleanup_on_schedule": bool(data.get("cleanup_on_schedule", previous["cleanup_on_schedule"])),
    }
    if settings["enabled"]:
        settings["next_run_at"] = _time_text(datetime.now() + timedelta(hours=settings["interval_hours"]))
    else:
        settings["next_run_at"] = ""
    _write_backup_settings(settings)
    if user:
        with connect() as conn:
            create_audit(conn, user.get("id"), "api_update_backup_settings", "database_backups", None, settings, previous)
            conn.commit()
    return {"item": settings}


def _write_backup_settings(settings: dict[str, Any]) -> None:
    BACKUP_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def start_scheduler() -> None:
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        _scheduler_stop.clear()
        _scheduler_thread = threading.Thread(target=_scheduler_loop, name="labkeeper-backup-scheduler", daemon=True)
        _scheduler_thread.start()


def stop_scheduler() -> None:
    _scheduler_stop.set()


def _scheduler_loop() -> None:
    while not _scheduler_stop.wait(60):
        try:
            _run_scheduler_tick()
        except Exception:
            logger.exception("定期备份调度异常")


def _run_scheduler_tick() -> None:
    settings = load_backup_settings()
    if not settings["enabled"]:
        return
    now = datetime.now()
    next_run = _time_from_text(settings.get("next_run_at"))
    if next_run is None:
        settings["next_run_at"] = _time_text(now + timedelta(hours=settings["interval_hours"]))
        _write_backup_settings(settings)
        return
    if now < next_run:
        return
    try:
        create_database_backup("scheduled", None)
        if settings["cleanup_on_schedule"]:
            cleanup_expired_backups(settings["retention_days"], None)
        settings["last_run_at"] = _time_text(now)
        settings["last_success_at"] = _time_text(now)
        settings["last_error"] = ""
        settings["next_run_at"] = _time_text(now + timedelta(hours=settings["interval_hours"]))
    except Exception as exc:
        logger.error("定期备份失败：%s", exc)
        settings["last_run_at"] = _time_text(now)
        settings["last_error"] = str(exc)
        settings["next_run_at"] = _time_text(now + timedelta(hours=max(1, settings["interval_hours"])))
    _write_backup_settings(settings)
