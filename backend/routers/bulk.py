from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from services import bulk_operations
from models.request_models import BulkExcelParseRequest, BulkOperationRequest
from routers.common import download_headers, json_response, strict_query_params
from core.security import require_permission, require_user

router = APIRouter(prefix="/api")


@router.get("/bulk/template")
def bulk_template(request: Request, user: dict[str, Any] = Depends(require_user)) -> Response:
    require_permission(user, "inventory.manage")
    query = strict_query_params(request, {"operation", "item_type"})
    body, content_type, filename = bulk_operations.template(query)
    return Response(content=body, media_type=content_type, headers=download_headers(filename, "bulk_template.xlsx"))


@router.get("/bulk/storage-map")
def bulk_storage_map(_: dict[str, Any] = Depends(require_user)) -> Response:
    body, content_type, filename = bulk_operations.storage_map()
    return Response(content=body, media_type=content_type, headers=download_headers(filename, "storage_map.xlsx"))


@router.get("/bulk/current-inventory")
def bulk_current_inventory(request: Request, user: dict[str, Any] = Depends(require_user)) -> Response:
    require_permission(user, "inventory.manage")
    query = strict_query_params(request, {"item_type"})
    body, content_type, filename = bulk_operations.current_inventory(query)
    return Response(content=body, media_type=content_type, headers=download_headers(filename, "current_inventory.xlsx"))


@router.post("/bulk/parse-excel")
def bulk_parse_excel(data: BulkExcelParseRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(bulk_operations.parse_excel(data.payload()))


@router.post("/bulk/preview")
def bulk_preview(data: BulkOperationRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(bulk_operations.preview(data.payload(), user))


@router.post("/bulk/commit")
def bulk_commit(data: BulkOperationRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(bulk_operations.commit(data.payload(), user))
