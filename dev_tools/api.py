from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from services import auth, backup
from core import config
from core.common import ApiError, now_text
from core.constants import STATUS_ORDERED, SYSTEM_NOT_ARRIVED_NODE_ID
from core.security import require_admin, require_user
from db import database
from routers.common import auth_cookie_response, json_response

router = APIRouter(prefix="/api/devtools")
DEMO_DB_PATH = config.ROOT / "dev_tools" / "demo.sqlite3"


def runtime_config() -> dict[str, Any]:
    enabled = config.ENABLE_DEVTOOLS
    return {
        "devtools_enabled": enabled,
        "devtools_admin_username": config.DEVTOOLS_ADMIN_USERNAME if enabled else "",
        "demo_database_available": DEMO_DB_PATH.exists() or _demo_builder_path().exists(),
    }


def require_enabled() -> None:
    if not config.ENABLE_DEVTOOLS:
        raise ApiError(403, "开发工具未启用")


def dev_admin_credentials() -> dict[str, str]:
    require_enabled()
    return {
        "username": config.DEVTOOLS_ADMIN_USERNAME,
        "password": config.DEVTOOLS_ADMIN_PASSWORD,
    }


def load_demo_database() -> dict[str, Any]:
    require_enabled()
    demo_db_path = DEMO_DB_PATH
    db_path = config.DB_PATH
    generated = _ensure_demo_database(demo_db_path)
    _assert_sqlite_ok(demo_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backup.stop_scheduler()
    try:
        backup_path = _backup_current_database(db_path)
        _replace_database_with_demo(demo_db_path, db_path)
        database.init_db()
    finally:
        backup.start_scheduler()
    stats = _database_stats(db_path)
    return {
        "ok": True,
        "message": "Demo 数据库已生成并载入" if generated else "Demo 数据库已载入",
        "backup": str(backup_path) if backup_path else "",
        "stats": stats,
    }


@router.get("/runtime-config")
def runtime_config_route() -> dict[str, Any]:
    return runtime_config()


@router.post("/login")
def devtools_login() -> JSONResponse:
    return auth_cookie_response(auth.login(dev_admin_credentials()))


@router.post("/load-demo-db")
def devtools_load_demo_database(user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(load_demo_database())


def _demo_builder_path() -> Path:
    return config.ROOT / "dev_tools" / "build_demo_db.py"


def _ensure_demo_database(path: Path) -> bool:
    if path.exists():
        return False
    builder_path = _demo_builder_path()
    if not builder_path.exists():
        raise ApiError(404, "Demo 数据库不存在，且缺少生成脚本 dev_tools/build_demo_db.py")
    spec = importlib.util.spec_from_file_location("labkeeper_demo_builder", builder_path)
    if spec is None or spec.loader is None:
        raise ApiError(500, "Demo 数据库生成脚本无法加载")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        build_demo_database = getattr(module, "build_demo_database")
        build_demo_database(path)
    except Exception as exc:
        raise ApiError(500, "Demo 数据库生成失败，请手动运行 dev_tools/build_demo_db.py") from exc
    if not path.exists():
        raise ApiError(500, "Demo 数据库生成后未找到")
    return True


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


def _replace_database_with_demo(demo_db_path: Path, db_path: Path) -> None:
    source = sqlite3.connect(demo_db_path)
    target = sqlite3.connect(db_path)
    try:
        target.execute("PRAGMA busy_timeout = 5000")
        source.backup(target)
        target.commit()
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        raise ApiError(500, "Demo 数据库载入失败，请关闭其他正在使用数据库的程序后重试") from exc
    finally:
        target.close()
        source.close()


def _database_stats(path: Path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        return {
            "users": int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]),
            "storage_nodes": int(conn.execute("SELECT COUNT(*) AS n FROM storage_nodes").fetchone()["n"]),
            "reagents": int(conn.execute("SELECT COUNT(*) AS n FROM reagents").fetchone()["n"]),
            "clinical_samples": int(conn.execute("SELECT COUNT(*) AS n FROM clinical_samples").fetchone()["n"]),
            "pending_orders": int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM reagents WHERE status = ? AND storage_node_id = ?",
                    (STATUS_ORDERED, SYSTEM_NOT_ARRIVED_NODE_ID),
                ).fetchone()["n"]
            ),
            "movements": int(conn.execute("SELECT COUNT(*) AS n FROM movements").fetchone()["n"]),
            "validations": int(conn.execute("SELECT COUNT(*) AS n FROM validations").fetchone()["n"]),
        }
    finally:
        conn.close()
