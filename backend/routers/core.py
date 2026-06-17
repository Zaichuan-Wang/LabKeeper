from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from services import admin
from services import auth
from core.common import ApiError, get_logger, now_text
from core.config import APP_VERSION, DB_PATH, IS_PRODUCTION
from models.request_models import LoginRequest, PasswordChangeRequest
from core.security import require_user
from routers.common import auth_cookie_response, clear_auth_cookie, json_response

router = APIRouter()
logger = get_logger("lab.server")

_login_failures: dict[str, list[float]] = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300


def _check_login_rate(client_ip: str) -> bool:
    now = time.monotonic()
    attempts = _login_failures.get(client_ip, [])
    attempts = [t for t in attempts if now - t < LOGIN_WINDOW_SECONDS]
    _login_failures[client_ip] = attempts
    return len(attempts) < LOGIN_MAX_ATTEMPTS


def _record_login_failure(client_ip: str) -> None:
    _login_failures.setdefault(client_ip, []).append(time.monotonic())


def _clear_login_failures(client_ip: str) -> None:
    _login_failures.pop(client_ip, None)


@router.get("/api/health")
def health() -> dict[str, Any]:
    payload = {"ok": True, "time": now_text(), "version": APP_VERSION}
    if not IS_PRODUCTION:
        payload["db"] = str(DB_PATH)
    return payload


@router.get("/api/options")
def options() -> dict[str, Any]:
    return admin.options()


@router.post("/api/login")
def login(request: Request, data: LoginRequest) -> JSONResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not _check_login_rate(client_ip):
        logger.warning("登录限流：%s", client_ip)
        raise ApiError(429, "登录尝试过于频繁，请 5 分钟后再试")
    try:
        result = auth.login(data.payload())
        _clear_login_failures(client_ip)
        logger.info("用户 %s 登录成功", data.payload().get("username", ""))
        return auth_cookie_response(result)
    except ApiError:
        _record_login_failure(client_ip)
        raise


@router.post("/api/logout")
def logout() -> JSONResponse:
    return clear_auth_cookie(json_response({"ok": True}))


@router.patch("/api/me/password")
def change_password(data: PasswordChangeRequest, user: dict[str, Any] = Depends(require_user)) -> JSONResponse:
    return json_response(auth.change_password(data.payload(), user))
