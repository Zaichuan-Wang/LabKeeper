from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from services import clinical_samples
from services import inventory
from services import reagents
from core.common import ApiError
from models.request_models import AliquotCreateRequest, InventoryItemCreateRequest, InventoryItemUpdateRequest
from core.security import require_permission, require_user

router = APIRouter(prefix="/api")


def json_response(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status_code)


def query_params(request: Request) -> dict[str, list[str]]:
    from urllib.parse import parse_qs

    return parse_qs(request.url.query)


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
    return inventory.search(query)


@router.get("/inventory/catalog-conflicts")
def catalog_conflicts(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    query = query_params(request)
    catalog_no = query.get("catalog_no", [""])[0]
    name = query.get("name", [""])[0]
    exclude_id = int(query.get("exclude_id", ["0"])[0] or 0) or None
    return reagents.catalog_name_conflicts(catalog_no, name, exclude_id)


@router.post("/inventory/items")
def create_inventory_item(data: InventoryItemCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(inventory.create_item(data.payload(), user), 201)


@router.get("/inventory/items/{item_type}/{item_id}")
def inventory_item_detail(item_type: str, item_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    return inventory.item_detail(item_type, item_id)


@router.get("/inventory/timeline")
def inventory_item_timeline(request: Request, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    query = query_params(request)
    item_type = query.get("item_type", ["reagent"])[0]
    item_id = int(query.get("id", ["0"])[0] or 0)
    if not item_id:
        raise ApiError(400, "库存对象不存在")
    return inventory.timeline(item_type, item_id)


@router.patch("/inventory/items/{item_type}/{item_id}")
def update_inventory_item(item_type: str, item_id: int, data: InventoryItemUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    return json_response(inventory.update_item(item_type, item_id, data.payload(patch=True), user))


@router.post("/aliquots")
def create_aliquots(data: AliquotCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "inventory.manage")
    payload = data.payload()
    if data.item_type == "sample":
        return json_response(clinical_samples.create_aliquots(payload, user), 201)
    return json_response(reagents.create_reagent_aliquots(payload, user), 201)
