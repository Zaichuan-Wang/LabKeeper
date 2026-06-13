from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "lab_inventory.sqlite3"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
DATA_DIR = ROOT / "data"
VALIDATION_IMAGE_DIR = DATA_DIR / "validation_images"
_options_config = Path(os.getenv("LAB_POSITION_OPTIONS_CONFIG", str(ROOT / "config" / "dropdown_options.json")))
OPTIONS_CONFIG_PATH = _options_config if _options_config.is_absolute() else ROOT / _options_config
_backup_settings = Path(os.getenv("LAB_POSITION_BACKUP_SETTINGS", str(ROOT / "config" / "backup_settings.json")))
BACKUP_SETTINGS_PATH = _backup_settings if _backup_settings.is_absolute() else ROOT / _backup_settings


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

SECRET = os.getenv("LAB_POSITION_API_SECRET", "lab-position-demo-secret-change-me")
TOKEN_TTL_SECONDS = int(os.getenv("LAB_POSITION_TOKEN_TTL_SECONDS", str(8 * 60 * 60)))
EXPIRATION_REMIND_DAYS = int(os.getenv("EXPIRATION_REMIND_DAYS", "30") or "30")
_cors_raw = os.getenv("LAB_POSITION_CORS_ORIGINS", "").strip()
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()] if _cors_raw else ["*"]
