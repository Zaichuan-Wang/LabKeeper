from __future__ import annotations

from typing import Any

from core.common import ApiError


def is_antibody_category(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return "抗体" in text or "antibody" in text


def antibody_name(target: Any, conjugate: Any) -> str:
    clean_target = str(target or "").strip()
    clean_conjugate = str(conjugate or "").strip()
    if not clean_target or not clean_conjugate:
        raise ApiError(400, "抗体必须填写靶标和颜色")
    return f"抗{clean_target}-{clean_conjugate}"


def apply_antibody_name_rule(data: dict[str, Any], *, name_key: str = "name") -> dict[str, Any]:
    if is_antibody_category(data.get("category")):
        data[name_key] = antibody_name(data.get("antibody_target"), data.get("antibody_conjugate"))
    return data
