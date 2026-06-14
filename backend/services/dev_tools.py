from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from services import backup
from core import config
from core.common import ApiError, now_text
from db.database import connect, init_db


def runtime_config() -> dict[str, Any]:
    return {
        "dev_tools_enabled": config.ENABLE_DEV_TOOLS,
        "dev_admin_username": config.DEV_ADMIN_USERNAME if config.ENABLE_DEV_TOOLS else "",
        "demo_database_available": config.DEMO_DB_PATH.exists(),
    }


def require_enabled() -> None:
    if not config.ENABLE_DEV_TOOLS:
        raise ApiError(403, "开发工具未启用")


def dev_admin_credentials() -> dict[str, str]:
    require_enabled()
    return {"username": config.DEV_ADMIN_USERNAME, "password": config.DEV_ADMIN_PASSWORD}


def load_demo_database() -> dict[str, Any]:
    require_enabled()
    demo_db_path = config.DEMO_DB_PATH
    db_path = config.DB_PATH
    if not demo_db_path.exists():
        _build_demo_database()
    _assert_sqlite_ok(demo_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup.stop_scheduler()
    try:
        backup_path = _backup_current_database(db_path)
        _remove_sqlite_files(db_path)
        shutil.copy2(demo_db_path, db_path)
        init_db()
    finally:
        backup.start_scheduler()
    stats = _database_stats(db_path)
    return {
        "ok": True,
        "message": "Demo 数据库已载入",
        "backup": str(backup_path) if backup_path else "",
        "stats": stats,
    }


def _assert_sqlite_ok(path: Path) -> None:
    conn = None
    try:
        conn = sqlite3.connect(path)
        row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise ApiError(500, "Demo 数据库无法读取") from exc
    finally:
        if conn is not None:
            conn.close()
    if not row or row[0] != "ok":
        raise ApiError(500, "Demo 数据库完整性检查失败")


def _build_demo_database() -> None:
    """Auto-generate demo.sqlite3 by running dev_tools/build_demo_db.py"""
    build_script = config.ROOT / "dev_tools" / "build_demo_db.py"
    if not build_script.exists():
        raise ApiError(500, "构建脚本不存在: dev_tools/build_demo_db.py")
    result = subprocess.run(
        [sys.executable, str(build_script)],
        capture_output=True,
        text=True,
        cwd=str(config.ROOT),
    )
    if result.returncode != 0:
        raise ApiError(500, f"生成 Demo 数据库失败: {result.stderr.strip()}")


def _backup_current_database(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir = db_path.parent / "dev_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_text().replace("-", "").replace(":", "").replace(" ", "_")
    backup_path = backup_dir / f"before_demo_{stamp}.sqlite3"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return backup_path


def _remove_sqlite_files(path: Path) -> None:
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists():
            candidate.unlink()


def _database_stats(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        return {
            "users": int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]),
            "storage_nodes": int(conn.execute("SELECT COUNT(*) AS n FROM storage_nodes").fetchone()["n"]),
            "reagents": int(conn.execute("SELECT COUNT(*) AS n FROM reagents").fetchone()["n"]),
            "clinical_samples": int(conn.execute("SELECT COUNT(*) AS n FROM clinical_samples").fetchone()["n"]),
            "orders": int(conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]),
            "validations": int(conn.execute("SELECT COUNT(*) AS n FROM validations").fetchone()["n"]),
        }
    finally:
        conn.close()
