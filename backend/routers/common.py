from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from core.common import ApiError


def json_response(payload: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)


def download_headers(filename: str, fallback: str = "download.xlsx") -> dict[str, str]:
    clean = filename.replace('"', "")
    return {"Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(clean)}"}


def query_params(request: Request) -> dict[str, list[str]]:
    return parse_qs(request.url.query)


def strict_query_params(request: Request, allowed: set[str]) -> dict[str, list[str]]:
    query = query_params(request)
    unknown = sorted(set(query) - allowed)
    if unknown:
        raise ApiError(400, "请求参数不正确")
    return query
