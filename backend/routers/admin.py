from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from services import admin
from services import backup
from services import data_health
from models.request_models import (
    AdminDeleteRecordRequest,
    BackupCleanupRequest,
    BackupCreateRequest,
    BackupSettingsRequest,
    DropdownSettingsRequest,
    ExcelImportRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from routers.common import download_headers, json_response, query_params
from core.security import require_admin, require_user

router = APIRouter(prefix="/api")


@router.get("/settings/dropdowns")
def dropdown_options(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return admin.dropdown_options()


@router.patch("/settings/dropdowns")
def update_dropdown_options(data: DropdownSettingsRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.update_dropdown_options(data.payload(patch=True), user))


@router.get("/users")
def users(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return admin.users()


@router.post("/users")
def create_user(data: UserCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.create_user(data.payload(), user), 201)


@router.patch("/users/{user_id}")
def update_user(user_id: int, data: UserUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.update_user(user_id, data.payload(patch=True), user))


@router.get("/admin/data-health")
def admin_data_health(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return data_health.report()


@router.get("/admin/backups")
def admin_backups(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return backup.list_database_backups()


@router.post("/admin/backups")
def create_admin_backup(data: BackupCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response({"item": backup.create_database_backup(data.reason, user)}, 201)


@router.post("/admin/backups/cleanup")
def cleanup_admin_backups(data: BackupCleanupRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(backup.cleanup_expired_backups(data.days or 30, user))


@router.get("/admin/backups/settings")
def admin_backup_settings(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return {"item": backup.load_backup_settings()}


@router.patch("/admin/backups/settings")
def update_admin_backup_settings(data: BackupSettingsRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(backup.save_backup_settings(data.payload(patch=True), user))


@router.get("/admin/backups/{filename}/download")
def download_admin_backup(filename: str, user: dict[str, Any] = Depends(require_user)) -> Response:
    require_admin(user)
    body, content_type, clean_filename = backup.backup_file(filename)
    return Response(content=body, media_type=content_type, headers=download_headers(clean_filename, "lab_inventory_backup.sqlite3"))


@router.delete("/admin/backups/{filename}")
def delete_admin_backup(filename: str, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(backup.delete_database_backup(filename, user))


@router.get("/excel/tables")
def excel_tables(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_admin(user)
    return admin.excel_tables()


@router.get("/excel/export")
def excel_export(request: Request, user: dict[str, Any] = Depends(require_user)) -> Response:
    require_admin(user)
    body, content_type, filename = admin.excel_export(query_params(request))
    return Response(content=body, media_type=content_type, headers=download_headers(filename, "excel_export.xlsx"))


@router.post("/excel/import")
def excel_import(data: ExcelImportRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.excel_import(data.payload(), user))


@router.post("/admin/records/delete")
def delete_admin_records(data: AdminDeleteRecordRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(admin.delete_records(data.payload(), user))
