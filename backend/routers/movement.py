from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from services import movements
from models.request_models import CheckoutCreateRequest, MovementCreateRequest
from routers.common import json_response
from core.security import require_inventory_view, require_permission, require_user, visible_inventory_types

router = APIRouter(prefix="/api")


@router.get("/movements")
def list_movements(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    return movements.list_movements(visible_inventory_types(user))


@router.post("/movements")
def create_movement(data: MovementCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    require_inventory_view(user, data.item_type)
    return json_response(movements.create_movement(data.payload(), user), 201)


@router.post("/movements/{movement_id}/rollback")
def rollback_movement(movement_id: int, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(movements.rollback_movement(movement_id, user), 201)


@router.get("/checkouts")
def list_checkouts(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    require_permission(user, "inventory.search")
    return movements.list_checkouts(visible_inventory_types(user))


@router.post("/checkouts")
def create_checkout(data: CheckoutCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_inventory_view(user, data.item_type)
    return json_response(movements.create_checkout(data.payload(), user), 201)
