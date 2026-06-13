from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from services import movements
from models.request_models import CheckoutCreateRequest, MovementCreateRequest
from routers.common import json_response
from core.security import require_permission, require_user

router = APIRouter(prefix="/api")


@router.get("/movements")
def list_movements(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return movements.list_movements()


@router.post("/movements")
def create_movement(data: MovementCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(movements.create_movement(data.payload(), user), 201)


@router.post("/movements/{movement_id}/rollback")
def rollback_movement(movement_id: int, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    require_permission(user, "location.manage")
    return json_response(movements.rollback_movement(movement_id, user), 201)


@router.get("/checkouts")
def list_checkouts(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return movements.list_checkouts()


@router.post("/checkouts")
def create_checkout(data: CheckoutCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(movements.create_checkout(data.payload(), user), 201)
