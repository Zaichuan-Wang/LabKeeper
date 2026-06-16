from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from services import clinical_samples
from services import inventory
from services import reagents
from core.common import ApiError, clean_optional_positive_int
from models.request_models import AliquotCreateRequest, InventoryItemCreateRequest, InventoryItemUpdateRequest
from routers.common import json_response, query_params
from core.security import require_inventory_view, require_permission, require_user, visible_inventory_types

router = APIRouter(prefix="/api")


def inventory_item_query(request: Request) -> tuple[str, int]:
    query = query_params(request)
    item_type = query.get("item_type", ["reagent"])[0]
    item_id = clean_optional_positive_int(query.get("id", [""])[0]) or 0
    if not item_id:
        raise ApiError(400, "库存对象不存在")
    return item_type, item_id


@router.get("/inventory/search")
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
    return inventory.search(query, visible_inventory_types(user))


@router.get("/inventory/catalog-conflicts")
def catalog_conflicts(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    query = query_params(request)
    catalog_no = query.get("catalog_no", [""])[0]
    name = query.get("name", [""])[0]
    exclude_id = clean_optional_positive_int(query.get("exclude_id", [""])[0])
    return reagents.catalog_name_conflicts(catalog_no, name, exclude_id)


@router.post("/inventory/items")
def create_inventory_item(data: InventoryItemCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(inventory.create_item(data.payload(), user), 201)


@router.get("/inventory/item")
def inventory_item_detail(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    item_type, item_id = inventory_item_query(request)
    require_inventory_view(user, inventory.clean_item_type(item_type))
    return inventory.item_detail(item_type, item_id)


@router.get("/inventory/timeline")
def inventory_item_timeline(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    item_type, item_id = inventory_item_query(request)
    require_inventory_view(user, inventory.clean_item_type(item_type))
    return inventory.timeline(item_type, item_id)


@router.patch("/inventory/item")
def update_inventory_item(request: Request, data: InventoryItemUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    item_type, item_id = inventory_item_query(request)
    require_inventory_view(user, inventory.clean_item_type(item_type))
    return json_response(inventory.update_item(item_type, item_id, data.payload(patch=True), user))


@router.post("/aliquots")
def create_aliquots(data: AliquotCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    payload = data.payload()
    require_permission(user, "inventory.manage")
    require_inventory_view(user, data.item_type)
    if data.item_type == "sample":
        return json_response(clinical_samples.create_aliquots(payload, user), 201)
    return json_response(reagents.create_reagent_aliquots(payload, user), 201)
