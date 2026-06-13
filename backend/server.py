from __future__ import annotations

import argparse
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import parse_qs, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Depends, FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import time

import admin
import auth
import backup
import bulk_operations
import clinical_samples
import data_health
import inventory
import movements
import reagents
import registration
from common import ApiError, get_logger, now_text
from config import CORS_ORIGINS, DB_PATH
from database import connect, init_db
from request_models import (
    AliquotCreateRequest,
    ArrivalCreateRequest,
    BackupCleanupRequest,
    BackupCreateRequest,
    BackupSettingsRequest,
    BulkExcelParseRequest,
    BulkOperationRequest,
    CheckoutCreateRequest,
    DropdownSettingsRequest,
    ExcelImportRequest,
    InventoryItemCreateRequest,
    InventoryItemUpdateRequest,
    LoginRequest,
    MovementCreateRequest,
    OrderCreateRequest,
    OrderUpdateRequest,
    PasswordChangeRequest,
    StorageNodeCreateRequest,
    StorageNodeUpdateRequest,
    UserCreateRequest,
    UserUpdateRequest,
    ValidationCreateRequest,
    ValidationImageUploadRequest,
)
import storage_api



@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    backup.start_scheduler()
    try:
        yield
    finally:
        backup.stop_scheduler()


logger = get_logger("lab.server")

app = FastAPI(title="Lab Position API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=86400,
)

_login_failures: dict[str, list[float]] = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300


def _check_login_rate(client_ip: str) -> bool:
    now = time.monotonic()
    attempts = _login_failures.get(client_ip, [])
    attempts = [t for t in attempts if now - t < LOGIN_WINDOW_SECONDS]
    _login_failures[client_ip] = attempts
    return len(attempts) < LOGIN_MAX_ATTEMPTS


def _record_login_failure(client_ip: str) -> None:
    _login_failures.setdefault(client_ip, []).append(time.monotonic())


def _clear_login_failures(client_ip: str) -> None:
    _login_failures.pop(client_ip, None)


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


def json_response(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)


def download_headers(filename: str, fallback: str = "download.xlsx") -> dict[str, str]:
    clean = filename.replace('"', "")
    return {"Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(clean)}"}


def query_params(request: Request) -> dict[str, list[str]]:
    return parse_qs(request.url.query)


def strict_query_params(request: Request, allowed: set[str]) -> dict[str, list[str]]:
    query = query_params(request)
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise ApiError(400, "请求参数不正确")
    return query


def require_user(request: Request) -> dict[str, Any]:
    user = auth.read_token(request.headers.get("Authorization"))
    if user is None:
        raise ApiError(401, "请先登录")
    return user


def require_admin(user: dict[str, Any]) -> None:
    if user.get("role") != "admin":
        raise ApiError(403, "当前账号没有管理员权限")


def require_permission(user: dict[str, Any], permission: str) -> None:
    if user.get("role") == "admin":
        return
    if not bool((user.get("permissions") or {}).get(permission)):
        raise ApiError(403, "当前账号没有该操作权限")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "db": str(DB_PATH), "time": now_text()}


@app.get("/api/options")
def options() -> dict[str, Any]:
    return admin.options()


@app.post("/api/login")
def login(request: Request, data: LoginRequest) -> JSONResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not _check_login_rate(client_ip):
        logger.warning("登录限流：%s", client_ip)
        raise ApiError(429, "登录尝试过于频繁，请 5 分钟后再试")
    try:
        result = auth.login(data.payload())
        _clear_login_failures(client_ip)
        logger.info("用户 %s 登录成功", data.payload().get("username", ""))
        return json_response(result)
    except ApiError:
        _record_login_failure(client_ip)
        raise


@app.get("/api/me")
def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {"user": user}


@app.patch("/api/me/password")
def change_password(data: PasswordChangeRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(auth.change_password(data.payload(), user))


@app.get("/api/dashboard")
def dashboard(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return reagents.dashboard()


@app.get("/api/inventory/search")
def inventory_search_route(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    query = query_params(request)
    purpose = query.get("purpose", ["global"])[0].strip() or "global"
    if purpose in {"global", "form", "validation"}:
        require_permission(user, "inventory.search")
    elif purpose == "movement":
        require_permission(user, "location.manage")
    elif purpose == "aliquot":
        require_permission(user, "inventory.manage")
    elif purpose == "checkout":
        pass
    else:
        raise ApiError(400, "库存搜索用途不正确")
    return inventory.search(query)


@app.get("/api/inventory/catalog-conflicts")
def catalog_conflicts(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    query = query_params(request)
    catalog_no = query.get("catalog_no", [""])[0]
    name = query.get("name", [""])[0]
    exclude_id = int(query.get("exclude_id", ["0"])[0] or 0) or None
    return reagents.catalog_name_conflicts(catalog_no, name, exclude_id)


@app.post("/api/inventory/items")
def create_inventory_item(data: InventoryItemCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(inventory.create_item(data.payload(), user), 201)


@app.get("/api/inventory/items/{item_type}/{item_id}")
def inventory_item_detail(item_type: str, item_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    return inventory.item_detail(item_type, item_id)


@app.get("/api/inventory/timeline")
def inventory_item_timeline(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    query = strict_query_params(request, {"item_type", "id"})
    item_type = query.get("item_type", ["reagent"])[0].strip() or "reagent"
    item_id = int(query.get("id", ["0"])[0] or 0)
    if item_type not in {"reagent", "sample"} or not item_id:
        raise ApiError(400, "库存时间线参数不正确")
    return inventory.timeline(item_type, item_id)


@app.patch("/api/inventory/items/{item_type}/{item_id}")
def update_inventory_item(item_type: str, item_id: int, data: InventoryItemUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(inventory.update_item(item_type, item_id, data.payload(patch=True), user))


@app.post("/api/aliquots")
def create_aliquots(data: AliquotCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    payload = data.payload()
    if data.item_type == "sample":
        return json_response(clinical_samples.create_aliquots(payload, user), 201)
    return json_response(reagents.create_reagent_aliquots(payload, user), 201)


@app.get("/api/orders")
def list_orders(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return registration.list_orders(query_params(request))


@app.post("/api/orders")
def create_order(data: OrderCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_order(data.payload(), user), 201)


@app.patch("/api/orders/{order_id}")
def update_order(order_id: int, data: OrderUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.update_order(order_id, data.payload(), user))


@app.get("/api/expiration")
def expiration(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return reagents.expiration(query_params(request))


@app.post("/api/uploads/validation-image")
def upload_validation_image(data: ValidationImageUploadRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.upload_validation_image(data.payload(), user), 201)


@app.get("/api/arrivals")
def list_arrivals(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return registration.list_arrivals()


@app.post("/api/arrivals")
def create_arrival(data: ArrivalCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_arrival(data.payload(), user), 201)


@app.get("/api/validations")
def list_validations(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return registration.list_validations()


@app.post("/api/validations")
def create_validation(data: ValidationCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_validation(data.payload(), user), 201)


@app.get("/api/movements")
def list_movements(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return movements.list_movements()


@app.post("/api/movements")
def create_movement(data: MovementCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(movements.create_movement(data.payload(), user), 201)


@app.post("/api/movements/{movement_id}/rollback")
def rollback_movement(movement_id: int, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(movements.rollback_movement(movement_id, user), 201)


@app.get("/api/checkouts")
def list_checkouts(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return movements.list_checkouts()


@app.post("/api/checkouts")
def create_checkout(data: CheckoutCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(movements.create_checkout(data.payload(), user), 201)


@app.get("/api/storage/tree")
def storage_tree(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return storage_api.storage_tree()


@app.get("/api/storage/visual")
def storage_visual(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    query = strict_query_params(request, {"node_id", "well", "item_type", "item_id"})
    node_id = int(query.get("node_id", ["0"])[0] or 0)
    selected_well = query.get("well", [""])[0].strip()
    item_type = query.get("item_type", [""])[0].strip()
    item_id = int(query.get("item_id", ["0"])[0] or 0)
    if item_type and item_type not in {"reagent", "sample"}:
        raise ApiError(400, "库存类型不正确")
    return storage_api.storage_visual(node_id or None, selected_well, item_type, item_id or None)


@app.post("/api/storage/nodes")
def create_storage_node(data: StorageNodeCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(storage_api.create_storage_node(data.payload(), user), 201)


@app.patch("/api/storage/nodes/{node_id}")
def update_storage_node(node_id: int, data: StorageNodeUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(storage_api.update_storage_node(node_id, data.payload(patch=True), user))


@app.delete("/api/storage/nodes/{node_id}")
def delete_storage_node(node_id: int, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(storage_api.delete_storage_node(node_id, user))


@app.get("/api/settings/dropdowns")
def dropdown_options(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return admin.dropdown_options()


@app.patch("/api/settings/dropdowns")
def update_dropdown_options(data: DropdownSettingsRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.update_dropdown_options(data.payload(), user))


@app.get("/api/users")
def users(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return admin.users()


@app.post("/api/users")
def create_user(data: UserCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.create_user(data.payload(), user), 201)


@app.patch("/api/users/{user_id}")
def update_user(user_id: int, data: UserUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.update_user(user_id, data.payload(patch=True), user))


@app.get("/api/admin/data-health")
def admin_data_health(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return data_health.report()


@app.get("/api/admin/backups")
def admin_backups(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return backup.list_database_backups()


@app.post("/api/admin/backups")
def create_admin_backup(data: BackupCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response({"item": backup.create_database_backup(data.reason, user)}, 201)


@app.post("/api/admin/backups/cleanup")
def cleanup_admin_backups(data: BackupCleanupRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(backup.cleanup_expired_backups(data.days or 30, user))


@app.get("/api/admin/backups/settings")
def admin_backup_settings(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return {"item": backup.load_backup_settings()}


@app.patch("/api/admin/backups/settings")
def update_admin_backup_settings(data: BackupSettingsRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(backup.save_backup_settings(data.payload(patch=True), user))


@app.get("/api/admin/backups/{filename}/download")
def download_admin_backup(filename: str, user: dict[str, Any] = Depends(require_user)) -> Response:
    require_admin(user)
    body, content_type, clean_filename = backup.backup_file(filename)
    return Response(content=body, media_type=content_type, headers=download_headers(clean_filename, "lab_inventory_backup.sqlite3"))


@app.delete("/api/admin/backups/{filename}")
def delete_admin_backup(filename: str, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(backup.delete_database_backup(filename, user))


@app.get("/api/excel/tables")
def excel_tables(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return admin.excel_tables()


@app.get("/api/excel/export")
def excel_export(request: Request, user: dict[str, Any] = Depends(require_user)) -> Response:
    require_admin(user)
    body, content_type, filename = admin.excel_export(query_params(request))
    headers: dict[str, str] = {}
    if filename:
        quoted = filename.replace('"', "")
        headers["Content-Disposition"] = f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quote(quoted)}"
    return Response(content=body, media_type=content_type, headers=headers)


@app.post("/api/excel/import")
def excel_import(data: ExcelImportRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.excel_import(data.payload(), user))


@app.get("/api/bulk/template")
def bulk_template(request: Request, user: dict[str, Any] = Depends(require_user)) -> Response:
    require_permission(user, "inventory.manage")
    query = strict_query_params(request, {"operation", "item_type"})
    body, content_type, filename = bulk_operations.template(query)
    return Response(content=body, media_type=content_type, headers=download_headers(filename, "bulk_template.xlsx"))


@app.get("/api/bulk/storage-map")
def bulk_storage_map(_: dict[str, Any] = Depends(require_user)) -> Response:
    body, content_type, filename = bulk_operations.storage_map()
    return Response(content=body, media_type=content_type, headers=download_headers(filename, "storage_map.xlsx"))


@app.get("/api/bulk/current-inventory")
def bulk_current_inventory(request: Request, user: dict[str, Any] = Depends(require_user)) -> Response:
    require_permission(user, "inventory.manage")
    query = strict_query_params(request, {"item_type"})
    body, content_type, filename = bulk_operations.current_inventory(query)
    return Response(content=body, media_type=content_type, headers=download_headers(filename, "current_inventory.xlsx"))


@app.post("/api/bulk/parse-excel")
def bulk_parse_excel(data: BulkExcelParseRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(bulk_operations.parse_excel(data.payload()))


@app.post("/api/bulk/preview")
def bulk_preview(data: BulkOperationRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(bulk_operations.preview(data.payload(), user))


@app.post("/api/bulk/commit")
def bulk_commit(data: BulkOperationRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(bulk_operations.commit(data.payload(), user))


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
    parser = argparse.ArgumentParser(description="Lab position backend API")
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
