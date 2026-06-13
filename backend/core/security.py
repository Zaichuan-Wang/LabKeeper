from __future__ import annotations

from typing import Any

from fastapi import Request

from services import auth
from core.common import ApiError

AUTH_COOKIE_NAME = "lp_token"


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
