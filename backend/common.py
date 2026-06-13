from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_logger_configured = False


def get_logger(name: str = "lab") -> logging.Logger:
    global _logger_configured
    logger = logging.getLogger(name)
    if _logger_configured:
        return logger
    _logger_configured = True
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    log_dir = Path(__file__).resolve().parents[1] / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(log_dir / "backend.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_dict(row) or {} for row in rows]


def safe_float(value: Any, default: float = 0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def create_audit(conn: sqlite3.Connection, user_id: int | None, action: str, table: str, target_id: int | None, new_value: Any = None, old_value: Any = None) -> None:
    conn.execute(
        """
        INSERT INTO audit_logs (user_id, action, target_table, target_id, old_value, new_value, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            action,
            table,
            target_id,
            json.dumps(old_value, ensure_ascii=False) if old_value is not None else None,
            json.dumps(new_value, ensure_ascii=False) if new_value is not None else None,
            now_text(),
        ),
    )
