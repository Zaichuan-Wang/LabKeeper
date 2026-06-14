from __future__ import annotations

import argparse
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from services import backup
from core.common import ApiError, get_logger
from core.config import CORS_ORIGINS, DB_PATH
from db.database import connect, init_db
from routers.admin import router as admin_router
from routers.bulk import router as bulk_router
from routers.core import router as core_router
from routers.inventory import router as inventory_router
from routers.movement import router as movement_router
from routers.registration import router as registration_router
from routers.storage import router as storage_router
from routers.common import json_response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    backup.start_scheduler()
    try:
        yield
    finally:
        backup.stop_scheduler()


logger = get_logger("lab.server")

app = FastAPI(title="LabKeeper API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=86400,
)
app.include_router(core_router)
app.include_router(inventory_router)
app.include_router(registration_router)
app.include_router(movement_router)
app.include_router(storage_router)
app.include_router(admin_router)
app.include_router(bulk_router)

@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return json_response({"error": exc.message}, exc.status)


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return json_response({"error": str(exc)}, 400)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return json_response({"error": "请求参数不正确"}, 400)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = "接口不存在" if exc.status_code == 404 else str(exc.detail)
    return json_response({"error": message}, exc.status_code)


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理的服务器错误")
    return json_response({"error": "服务器内部错误，请稍后重试"}, 500)


def run_check() -> None:
    init_db()
    with connect() as conn:
        users_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        reagents_count = conn.execute("SELECT COUNT(*) AS n FROM reagents").fetchone()["n"]
        samples = conn.execute("SELECT COUNT(*) AS n FROM clinical_samples").fetchone()["n"]
        orders = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
    result = {"ok": True, "db": str(DB_PATH), "users": users_count, "reagents": reagents_count, "clinical_samples": samples, "orders": orders}
    logger.info("数据库检查：%s", json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="LabKeeper backend API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true", help="初始化并检查数据库后退出")
    args = parser.parse_args()
    if args.check:
        run_check()
        return
    init_db()
    import uvicorn

    logger.info("API server running: http://%s:%s/api/health", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
