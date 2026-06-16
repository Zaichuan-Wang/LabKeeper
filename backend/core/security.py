from __future__ import annotations

from typing import Any

from fastapi import Request

from services import auth
from core.common import ApiError

AUTH_COOKIE_NAME = "labkeeper_token"


def require_user(request: Request) -> dict[str, Any]:
    auth_header = request.headers.get("Authorization")
    if not auth_header and request.cookies.get(AUTH_COOKIE_NAME):
        auth_header = f"Bearer {request.cookies.get(AUTH_COOKIE_NAME)}"
    user = auth.read_token(auth_header)
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


def can_view_inventory_type(user: dict[str, Any], item_type: str) -> bool:
    if user.get("role") == "admin":
        return True
    permission = "inventory.view_samples" if item_type == "sample" else "inventory.view_reagents"
    return bool((user.get("permissions") or {}).get(permission))


def visible_inventory_types(user: dict[str, Any]) -> set[str]:
    return {item_type for item_type in ("reagent", "sample") if can_view_inventory_type(user, item_type)}


def require_inventory_view(user: dict[str, Any], item_type: str) -> None:
    clean_type = "sample" if item_type == "sample" else "reagent"
    if not can_view_inventory_type(user, clean_type):
        label = "临床标本" if clean_type == "sample" else "试剂"
        raise ApiError(403, f"当前账号没有查看{label}权限")
