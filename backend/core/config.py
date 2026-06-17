from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "db" / "lab_inventory.sqlite3"
SCHEMA_PATH = ROOT / "backend" / "db" / "schema.sql"
DATA_DIR = ROOT / "data"
VALIDATION_IMAGE_DIR = DATA_DIR / "validation_images"
ENV_PATH = ROOT / "config" / ".env"


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(ENV_PATH)


def env_value(name: str, default: str = "") -> str:
    return os.getenv(f"LABKEEPER_{name}", default)


def env_flag(name: str, default: bool = False) -> bool:
    raw = env_value(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def env_path(name: str, default: Path) -> Path:
    raw = Path(env_value(name, str(default)))
    return raw if raw.is_absolute() else ROOT / raw


APP_ENV = env_value("ENV", "production").strip().lower() or "production"
IS_PRODUCTION = APP_ENV in {"production", "prod"}
INITIAL_ADMIN_USERNAME = env_value("INITIAL_ADMIN_USERNAME", "admin")
INITIAL_PASSWORD = env_value("INITIAL_PASSWORD", "" if IS_PRODUCTION else "admin123")
INITIAL_ADMIN_DISPLAY_NAME = env_value("INITIAL_ADMIN_DISPLAY_NAME", "管理员")
ENABLE_DEVTOOLS = (not IS_PRODUCTION) and env_flag("ENABLE_DEVTOOLS", APP_ENV in {"development", "dev", "test"})
DEVTOOLS_ADMIN_USERNAME = env_value("DEVTOOLS_ADMIN_USERNAME", "admin")
DEVTOOLS_ADMIN_PASSWORD = env_value("DEVTOOLS_ADMIN_PASSWORD", "admin123")

OPTIONS_CONFIG_PATH = env_path("OPTIONS_CONFIG", ROOT / "config" / "dropdown_options.json")
BACKUP_SETTINGS_PATH = env_path("BACKUP_SETTINGS", ROOT / "config" / "backup_settings.json")


SECRET = env_value("API_SECRET", "labkeeper-dev-secret-change-me")
TOKEN_TTL_SECONDS = int(env_value("TOKEN_TTL_SECONDS", str(8 * 60 * 60)))
EXPIRATION_REMIND_DAYS = int(env_value("EXPIRATION_REMIND_DAYS", "30") or "30")
QWEN_API_KEY = env_value("QWEN_API_KEY", "").strip()
QWEN_BASE_URL = env_value("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").strip().rstrip("/")
QWEN_MODEL = env_value("QWEN_MODEL", "qwen3.7-plus").strip() or "qwen3.7-plus"
# Qwen 联网搜索通常比普通 API 慢，默认留足一点等待时间。
QWEN_TIMEOUT_SECONDS = float(env_value("QWEN_TIMEOUT_SECONDS", "60") or "60")
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

INSECURE_INITIAL_PASSWORD_VALUES = {
    "",
    "admin123",
    "change-this-admin-password",
    "change-this-initial-password",
}
if IS_PRODUCTION and INITIAL_PASSWORD in INSECURE_INITIAL_PASSWORD_VALUES:
    raise RuntimeError("生产环境必须设置安全的 LABKEEPER_INITIAL_PASSWORD")
