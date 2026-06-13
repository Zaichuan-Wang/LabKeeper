from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "db" / "lab_inventory.sqlite3"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
DATA_DIR = ROOT / "data"
VALIDATION_IMAGE_DIR = DATA_DIR / "validation_images"


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


def env_value(name: str, default: str = "") -> str:
    return os.getenv(f"LABKEEPER_{name}", default)


def env_flag(name: str, default: bool = False) -> bool:
    raw = env_value(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


APP_ENV = env_value("ENV", "production").strip().lower() or "production"
IS_PRODUCTION = APP_ENV in {"production", "prod"}
ENABLE_DEV_TOOLS = (not IS_PRODUCTION) and env_flag("ENABLE_DEV_TOOLS", APP_ENV in {"development", "dev", "test"})
DEV_ADMIN_USERNAME = env_value("DEV_ADMIN_USERNAME", "admin")
DEV_ADMIN_PASSWORD = env_value("DEV_ADMIN_PASSWORD", "admin123")
INITIAL_ADMIN_USERNAME = env_value("INITIAL_ADMIN_USERNAME", DEV_ADMIN_USERNAME)
INITIAL_ADMIN_PASSWORD = env_value("INITIAL_ADMIN_PASSWORD", "" if IS_PRODUCTION else DEV_ADMIN_PASSWORD)
INITIAL_ADMIN_DISPLAY_NAME = env_value("INITIAL_ADMIN_DISPLAY_NAME", "管理员")

_options_config = Path(env_value("OPTIONS_CONFIG", str(ROOT / "config" / "dropdown_options.json")))
OPTIONS_CONFIG_PATH = _options_config if _options_config.is_absolute() else ROOT / _options_config
_backup_settings = Path(env_value("BACKUP_SETTINGS", str(ROOT / "config" / "backup_settings.json")))
BACKUP_SETTINGS_PATH = _backup_settings if _backup_settings.is_absolute() else ROOT / _backup_settings
DEMO_DB_PATH = ROOT / "dev_tools" / "demo.sqlite3"


SECRET = env_value("API_SECRET", "labkeeper-dev-secret-change-me")
TOKEN_TTL_SECONDS = int(env_value("TOKEN_TTL_SECONDS", str(8 * 60 * 60)))
EXPIRATION_REMIND_DAYS = int(env_value("EXPIRATION_REMIND_DAYS", "30") or "30")
_cors_raw = env_value("CORS_ORIGINS", "").strip()
LOCAL_CORS_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()] if _cors_raw else LOCAL_CORS_ORIGINS

INSECURE_SECRET_VALUES = {
    "",
    "labkeeper-dev-secret-change-me",
    "change-this-secret-before-shared-deployment",
}
if IS_PRODUCTION and SECRET in INSECURE_SECRET_VALUES:
    raise RuntimeError("生产环境必须设置 LABKEEPER_API_SECRET")
if IS_PRODUCTION and not _cors_raw:
    raise RuntimeError("生产环境必须设置 LABKEEPER_CORS_ORIGINS")
