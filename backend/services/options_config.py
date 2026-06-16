from __future__ import annotations

import json
import re
from typing import Any

from core.constants import REAGENT_STATUSES, SAMPLE_STATUSES, VALIDATION_STATUSES
from core.config import OPTIONS_CONFIG_PATH


DEFAULT_DROPDOWN_SETTINGS = {
    "categories": ["抗体", "试剂盒", "耗材", "细胞因子", "培养基", "缓冲液", "染料", "酶", "其他"],
    "brands": [
        "Sigma-Aldrich",
        "Thermo Fisher",
        "Abcam",
        "CST",
        "BioLegend",
        "BD Biosciences",
        "Invitrogen",
        "R&D Systems",
        "Gibco",
        "Corning",
        "碧云天",
        "索莱宝",
        "翌圣生物",
    ],
    "reagent_statuses": list(REAGENT_STATUSES),
    "validation_statuses": list(VALIDATION_STATUSES),
    "validation_methods": ["WB", "荧光", "流式", "IHC", "ELISA", "qPCR", "其他"],
    "sample_prefixes": ["SMP"],
    "sample_names": ["血清", "血浆", "全血", "细胞悬液", "组织", "灌洗液", "尿液", "其他", "细胞", "匀浆"],
    "amount_units": ["mL", "uL", "L", "g", "mg", "ug", "ng"],
    "sample_statuses": list(SAMPLE_STATUSES),
    "space_types": ["盒子", "冰箱", "液氮罐", "架子", "其他"],
    "movement_merge_window_minutes": 30,
}

FIXED_DROPDOWN_SETTINGS = {
    "reagent_statuses": DEFAULT_DROPDOWN_SETTINGS["reagent_statuses"],
    "validation_statuses": DEFAULT_DROPDOWN_SETTINGS["validation_statuses"],
    "sample_statuses": DEFAULT_DROPDOWN_SETTINGS["sample_statuses"],
    "space_types": ["其他"],
}

SPACE_TYPE_DEFAULTS = DEFAULT_DROPDOWN_SETTINGS["space_types"]
SPACE_TYPE_CODES = ("1", "2", "3", "4", "5")


def normalize_space_types(values: Any, fallback: list[str] | None = None) -> list[str]:
    def raw_list(raw: Any) -> list[str]:
        if isinstance(raw, str):
            return [str(value).strip() for value in re.split(r"[\n,，;；]+", raw)]
        if isinstance(raw, (list, tuple)):
            return [str(value).strip() for value in raw]
        return []

    defaults = raw_list(SPACE_TYPE_DEFAULTS)
    source = raw_list(values)
    fallback_values = raw_list(fallback)
    result: list[str] = []
    for index in range(4):
        if index < len(source):
            value = source[index]
        elif index < len(fallback_values):
            value = fallback_values[index]
        else:
            value = defaults[index]
        if value == "其他":
            value = ""
        result.append(value)
    return result + ["其他"]


def clean_space_type_code(value: Any) -> int:
    try:
        raw = str(value).strip()
        if not raw or raw not in SPACE_TYPE_CODES:
            raise ValueError
        code = int(raw)
    except (TypeError, ValueError):
        raise ValueError("空间类型必须是 1 到 5")
    return code


def space_type_label(value: Any, labels: list[str] | None = None) -> str:
    labels = normalize_space_types(labels or SPACE_TYPE_DEFAULTS)
    try:
        code = clean_space_type_code(value)
    except ValueError:
        code = 5
    label = labels[code - 1]
    return label or (f"类型 {code}" if code < 5 else "其他")


def clean_options(values: Any) -> list[str]:
    if isinstance(values, str):
        raw_values = re.split(r"[\n,，;；]+", values)
    elif isinstance(values, (list, tuple, set)):
        raw_values = values
    else:
        raw_values = []
    cleaned: list[str] = []
    for value in raw_values:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def normalize_dropdown_options(data: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    source = data if isinstance(data, dict) else {}
    base = fallback or DEFAULT_DROPDOWN_SETTINGS
    clean: dict[str, Any] = {}
    for key, defaults in DEFAULT_DROPDOWN_SETTINGS.items():
        values = source.get(key, base.get(key, defaults))
        if key == "movement_merge_window_minutes":
            clean[key] = clean_movement_merge_window(values)
            continue
        if key in FIXED_DROPDOWN_SETTINGS:
            required = clean_options(FIXED_DROPDOWN_SETTINGS[key])
            if key == "space_types":
                clean[key] = normalize_space_types(values, base.get(key, defaults))
                continue
            custom = [value for value in clean_options(values) if value not in required]
            clean[key] = required + custom
            continue
        clean[key] = clean_options(values) or clean_options(defaults)
    return clean


def clean_movement_merge_window(value: Any) -> int:
    try:
        minutes = int(float(value))
    except (TypeError, ValueError):
        minutes = int(DEFAULT_DROPDOWN_SETTINGS["movement_merge_window_minutes"])
    return max(0, min(minutes, 24 * 60))


def load_dropdown_options() -> dict[str, Any]:
    if not OPTIONS_CONFIG_PATH.exists():
        return normalize_dropdown_options({})
    try:
        saved = json.loads(OPTIONS_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"选项配置文件不是合法 JSON：{OPTIONS_CONFIG_PATH}") from exc
    return normalize_dropdown_options(saved)


def save_dropdown_options(data: Any) -> dict[str, Any]:
    clean = normalize_dropdown_options(data, load_dropdown_options())
    OPTIONS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OPTIONS_CONFIG_PATH.with_name(f"{OPTIONS_CONFIG_PATH.name}.tmp")
    tmp_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")
    tmp_path.replace(OPTIONS_CONFIG_PATH)
    return clean


def dropdown_values(key: str) -> list[str]:
    values = load_dropdown_options().get(key, clean_options(DEFAULT_DROPDOWN_SETTINGS.get(key, [])))
    return values if isinstance(values, list) else []
