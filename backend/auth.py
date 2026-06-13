from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import database
from common import ApiError, create_audit, now_text
from config import SECRET, TOKEN_TTL_SECONDS
from constants import DEFAULT_USER_PERMISSIONS, PERMISSIONS

HASH_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, HASH_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        HASH_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def make_token(user: dict[str, Any]) -> str:
    payload = {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user["role"],
        "permissions": user.get("permissions") or {},
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    body = _b64url(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(auth_header: str | None) -> dict[str, Any] | None:
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    try:
        body, sig = token.split(".", 1)
        expected = _b64url(hmac.new(SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        with database.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (payload.get("id"),)).fetchone()
        if row is None or int(row["is_active"]) != 1:
            return None
        user = public_user(row)
        user["exp"] = payload.get("exp")
        return user
    except Exception:
        return None


def login(data: dict[str, Any]) -> dict[str, Any]:
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or not password:
        raise ApiError(400, "请输入用户名和密码")
    with database.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None or int(row["is_active"]) != 1 or not verify_password(password, row["password_hash"]):
            raise ApiError(401, "用户名或密码不正确")
        user = public_user(row)
        conn.execute(
            "INSERT INTO audit_logs (user_id, action, target_table, target_id, created_at) VALUES (?, 'api_login', 'users', ?, ?)",
            (user["id"], user["id"], now_text()),
        )
        conn.commit()
    return {"token": make_token(user), "user": user}


def change_password(data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    old_password = str(data.get("old_password", ""))
    new_password = str(data.get("new_password", ""))
    if not old_password or not new_password:
        raise ApiError(400, "旧密码和新密码不能为空")
    if len(new_password) < 6:
        raise ApiError(400, "新密码至少 6 位")
    with database.connect() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if row is None or not verify_password(old_password, row["password_hash"]):
            raise ApiError(400, "旧密码不正确")
        conn.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (hash_password(new_password), now_text(), user["id"]))
        create_audit(conn, user["id"], "api_change_password", "users", user["id"])
        conn.commit()
    return {"ok": True}


def public_user(row: Any) -> dict[str, Any]:
    role = row["role"]
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "role": role,
        "permissions": user_permissions(row["permissions"] if not isinstance(row, dict) else row.get("permissions"), role),
        "is_active": row.get("is_active", 1) if isinstance(row, dict) else row["is_active"],
    }


def user_permissions(raw: str | dict[str, Any] | None, role: str | None = "user") -> dict[str, bool]:
    if role == "admin":
        return {key: True for key in PERMISSIONS}
    values = DEFAULT_USER_PERMISSIONS.copy()
    if isinstance(raw, dict):
        source = raw
    else:
        try:
            source = json.loads(raw or "{}")
        except json.JSONDecodeError:
            source = {}
    if isinstance(source, dict):
        for key in values:
            if key in source:
                values[key] = bool(source[key])
    return values


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
