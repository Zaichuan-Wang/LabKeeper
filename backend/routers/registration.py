from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse

from core.common import ApiError
from core.config import VALIDATION_IMAGE_DIR
from services import reagents
from services import registration
from models.request_models import (
    ArrivalCreateRequest,
    OrderCreateRequest,
    ValidationCreateRequest,
    ValidationImageUploadRequest,
    ValidationUpdateRequest,
)
from routers.common import json_response, query_params
from core.security import require_inventory_view, require_permission, require_user, visible_inventory_types

router = APIRouter(prefix="/api")


@router.get("/dashboard")
def dashboard(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return reagents.dashboard(visible_inventory_types(user))


@router.get("/orders")
def list_orders(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_inventory_view(user, "reagent")
    query = query_params(request)
    purpose = query.get("purpose", ["history"])[0]
    if purpose == "form":
        query["status"] = ["未到货"]
    else:
        require_permission(user, "inventory.search")
    return registration.list_orders(query)


@router.post("/orders")
def create_order(data: OrderCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_order(data.payload(), user), 201)


@router.get("/expiration")
def expiration(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if "reagent" not in visible_inventory_types(user):
        return {"overdue": [], "upcoming": [], "pending_orders": [], "unvalidated_antibodies": [], "remind_days": 0}
    return reagents.expiration(query_params(request))


@router.post("/uploads/validation-image")
def upload_validation_image(data: ValidationImageUploadRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.upload_validation_image(data.payload(), user), 201)


@router.get("/validation-images/{filename}")
def validation_image(filename: str, _: dict[str, Any] = Depends(require_user)) -> FileResponse:
    if Path(filename).name != filename:
        raise ApiError(400, "图片路径不正确")
    root = VALIDATION_IMAGE_DIR.resolve()
    path = (root / filename).resolve()
    if path.parent != root:
        raise ApiError(400, "图片路径不正确")
    if not path.is_file():
        raise ApiError(404, "验证图片不存在")
    return FileResponse(path)


@router.post("/arrivals")
def create_arrival(data: ArrivalCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_arrival(data.payload(), user), 201)


@router.get("/validations")
def list_validations(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    require_inventory_view(user, "reagent")
    return registration.list_validations()


@router.post("/validations")
def create_validation(data: ValidationCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_validation(data.payload(), user), 201)


@router.patch("/validations/{validation_id}")
def update_validation(validation_id: int, data: ValidationUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.update_validation(validation_id, data.payload(patch=True), user))
