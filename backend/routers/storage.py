from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from services import storage_api
from core.common import ApiError, clean_optional_positive_int
from models.request_models import StorageNodeCreateRequest, StorageNodeUpdateRequest
from routers.common import json_response, strict_query_params
from core.security import require_admin, require_permission, require_user

router = APIRouter(prefix="/api")


@router.get("/storage/tree")
def storage_tree(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return storage_api.storage_tree()


@router.get("/storage/visual")
def storage_visual(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    query = strict_query_params(request, {"node_id", "well", "item_type", "item_id"})
    node_id = clean_optional_positive_int(query.get("node_id", [""])[0])
    selected_well = query.get("well", [""])[0].strip()
    item_type = query.get("item_type", [""])[0].strip()
    item_id = clean_optional_positive_int(query.get("item_id", [""])[0])
    if item_type and item_type not in {"reagent", "sample"}:
        raise ApiError(400, "库存类型不正确")
    return storage_api.storage_visual(node_id, selected_well, item_type, item_id)


@router.post("/storage/nodes")
def create_storage_node(data: StorageNodeCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(storage_api.create_storage_node(data.payload(), user), 201)


@router.patch("/storage/nodes/{node_id}")
def update_storage_node(node_id: int, data: StorageNodeUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(storage_api.update_storage_node(node_id, data.payload(patch=True), user))


@router.delete("/storage/nodes/{node_id}")
def delete_storage_node(node_id: int, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_admin(user)
    return json_response(storage_api.delete_storage_node(node_id, user))
