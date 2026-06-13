from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from services import reagents
from services import registration
from models.request_models import (
    ArrivalCreateRequest,
    OrderCreateRequest,
    OrderUpdateRequest,
    ValidationCreateRequest,
    ValidationImageUploadRequest,
)
from routers.common import json_response, query_params
from core.security import require_user

router = APIRouter(prefix="/api")


@router.get("/dashboard")
def dashboard(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return reagents.dashboard()


@router.get("/orders")
def list_orders(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return registration.list_orders(query_params(request))


@router.post("/orders")
def create_order(data: OrderCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_order(data.payload(), user), 201)


@router.patch("/orders/{order_id}")
def update_order(order_id: int, data: OrderUpdateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.update_order(order_id, data.payload(), user))


@router.get("/expiration")
def expiration(request: Request, _: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return reagents.expiration(query_params(request))


@router.post("/uploads/validation-image")
def upload_validation_image(data: ValidationImageUploadRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.upload_validation_image(data.payload(), user), 201)


@router.get("/arrivals")
def list_arrivals(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return registration.list_arrivals()


@router.post("/arrivals")
def create_arrival(data: ArrivalCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_arrival(data.payload(), user), 201)


@router.get("/validations")
def list_validations(_: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return registration.list_validations()


@router.post("/validations")
def create_validation(data: ValidationCreateRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(registration.create_validation(data.payload(), user), 201)
