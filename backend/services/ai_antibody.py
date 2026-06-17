from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote, urlparse

from core import config
from core.common import ApiError, get_logger
from services.antibody_metadata import METADATA_FIELDS


TEXT_LIMITS = {
    "target": 120,
    "conjugate": 120,
    "react_species": 160,
    "host_species": 160,
    "clone": 120,
    "isotype": 160,
    "aliases": 240,
    "raw_note": 800,
}
REAGENT_FIELDS = ("name", "category", "brand", "catalog_no", "amount", "amount_unit", "quantity", "price", "reason", "note")
URL_PATTERN = re.compile(r"https?://[^\s，。；;,]+|www\.[^\s，。；;,]+", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-+][A-Za-z0-9]+)*")
UNLABELED_CONJUGATE_ALIASES = {
    "unlabeled",
    "unlabelled",
    "unconjugated",
    "purified",
    "indirect",
    "none",
    "no label",
    "no-label",
    "no fluorophore",
    "no enzyme",
    "未标记",
    "无标记",
    "未偶联",
    "无偶联",
    "间接",
    "间标",
}
UNLABELED_CONTEXT_ALIASES = UNLABELED_CONJUGATE_ALIASES - {"indirect", "间接", "间标"}

logger = get_logger("lab.ai_antibody")


def _clean_text(value: Any, limit: int = 240) -> str:
    if isinstance(value, list):
        value = "、".join(str(item).strip() for item in value if str(item).strip())
    text = str(value or "").strip()
    return text[:limit]


def _clean_warnings(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = []
    return [_clean_text(item, 160) for item in items if _clean_text(item, 160)][:5]


def _clean_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(number, 1.0))


def _clean_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_options(value: Any, limit: int = 80) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _clean_text(item, limit)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:80]


def _unique(items: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = _clean_text(item, 200)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _unlabeled_key(value: Any) -> str:
    return re.sub(r"[\s_\-/,，。()（）]+", " ", str(value or "").strip().lower()).strip()


def _looks_unlabeled(value: Any, aliases: set[str] | None = None) -> bool:
    aliases = aliases or UNLABELED_CONJUGATE_ALIASES
    text = _unlabeled_key(value)
    if not text:
        return False
    return text in aliases or any(alias in text for alias in aliases)


def _normalize_antibody_conjugate(value: Any, *context: Any) -> str:
    text = _clean_text(value, TEXT_LIMITS["conjugate"])
    if _looks_unlabeled(text) or (not text and any(_looks_unlabeled(item, UNLABELED_CONTEXT_ALIASES) for item in context)):
        return "Unlabeled"
    return text


def _url_search_text(url: str) -> str:
    normalized = url if url.lower().startswith(("http://", "https://")) else f"https://{url}"
    parsed = urlparse(normalized)
    host = parsed.netloc.removeprefix("www.")
    path = unquote(f"{parsed.path} {parsed.query}")
    words = [word for word in re.split(r"[-_/?.=&]+", path) if len(word) > 1]
    return " ".join([host, *words[:24]]).strip()


def _catalog_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_PATTERN.findall(text):
        clean = token.strip("-+")
        if not clean:
            continue
        if re.search(r"\d", clean):
            tokens.append(clean)
        tokens.extend(match.group(0) for match in re.finditer(r"(?i)ab\d{3,}", clean))
        species_match = re.match(r"(?i)^(goat|mouse|rabbit|rat|human)([a-z]{1,4}\d{3,})$", clean)
        if species_match:
            tokens.extend([species_match.group(1), species_match.group(2)])
    return _unique(tokens, 10)


def _search_queries(data: dict[str, Any]) -> list[str]:
    text = _clean_text(data.get("text"), 4000)
    brands = _clean_options(data.get("brands"), 120)
    urls = _unique(URL_PATTERN.findall(text), 3)
    url_words = [_url_search_text(url) for url in urls]
    catalog_tokens = _catalog_tokens(text)
    lower_text = text.lower()
    matched_brands = [brand for brand in brands if brand.lower() in lower_text]
    if "abcam" in lower_text and not any(brand.lower() == "abcam" for brand in matched_brands):
        matched_brands.append("Abcam")
    biological_terms = [
        token
        for token in TOKEN_PATTERN.findall(text)
        if re.search(r"[A-Za-z]", token) and ("-" in token or token.upper().startswith(("CD", "IL", "NK", "PD", "EGF", "TNF")))
    ]
    query_parts = _unique([*matched_brands[:2], *catalog_tokens[:4], *biological_terms[:4]], 8)
    queries = [*urls, *url_words]
    if query_parts:
        queries.append(" ".join(query_parts))
    if matched_brands and catalog_tokens:
        queries.append(" ".join([matched_brands[0], catalog_tokens[0]]))
    if text and len(text) <= 200:
        queries.append(text)
    return _unique(queries, 6)


def _parse_json_object(content: str) -> dict[str, Any]:
    raw = str(content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ApiError(502, "AI 没有返回可解析的抗体信息")
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ApiError(502, "AI 返回的抗体信息格式不正确") from exc
    if not isinstance(data, dict):
        raise ApiError(502, "AI 返回的抗体信息格式不正确")
    return data


def _extract_messages(data: dict[str, Any]) -> list[dict[str, str]]:
    categories = _clean_options(data.get("categories"), 80)
    brands = _clean_options(data.get("brands"), 120)
    amount_units = _clean_options(data.get("amount_units"), 40)
    search_queries = _search_queries(data)
    schema = {
        "name": "",
        "category": "",
        "brand": "",
        "catalog_no": "",
        "amount": None,
        "amount_unit": "",
        "quantity": None,
        "price": None,
        "reason": "",
        "note": "",
        "is_antibody": False,
        "antibody": {field: "" for field in METADATA_FIELDS},
        "confidence": 0.0,
        "warnings": [],
    }
    return [
        {
            "role": "system",
            "content": (
                "你是实验室试剂登记信息提取助手。"
                "用户会给一段自由文本、采购描述或产品链接。你需要优先联网检索链接或产品页，"
                "再把可确认的信息结构化为 JSON。不要猜测；无法确认的字段留空或 null。"
                "只要输入中有链接、品牌、货号或疑似货号，必须先使用 web_search 检索 search_queries，"
                "不要只根据用户输入直接作答；如搜索结果不足，在 warnings 中说明。"
                "category 必须从用户给定 categories 中选择，不能自造；如果都不合适，选择最接近的“其他”。"
                "brand 必须先把网页或描述中的厂家名、品牌名、子品牌、并购前后名称与用户给定 brands 对照；"
                "如果能判断为同一公司或常见别名，返回 brands 中已有的写法；"
                "只有明显都不属于已有 brands 时才填写新品牌名。"
                "amount_unit 优先从用户给定 amount_units 中选择；不合适时可以留空。"
                "抗体的 antibody.conjugate 只记录抗体本身实际偶联的标记；直接标记抗体填写 FITC、APC、HRP、AF488 等，"
                "未偶联、unlabeled、unconjugated 或 purified 一抗统一填写 Unlabeled；二抗填写它本身的实际标记。"
                "不要把间接法写成 Indirect。"
                "只输出一个 JSON object，不要输出解释文字。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "从自由文本或链接提取试剂登记字段",
                    "form_context": _clean_text(data.get("form_context"), 40),
                    "text_or_url": _clean_text(data.get("text"), 4000),
                    "search_queries": search_queries,
                    "search_policy": "search_queries 非空时必须先联网检索，再根据公开产品页或可靠经销商页面提取字段",
                    "allowed_options": {
                        "categories": categories,
                        "brands": brands,
                        "amount_units": amount_units,
                        "antibody_conjugates": _clean_options(data.get("antibody_conjugates"), 80),
                        "antibody_react_species": _clean_options(data.get("antibody_react_species"), 80),
                        "antibody_host_species": _clean_options(data.get("antibody_host_species"), 80),
                        "antibody_isotypes": _clean_options(data.get("antibody_isotypes"), 80),
                    },
                    "required_json_schema": schema,
                    "field_notes": {
                        "name": "产品或试剂名称，抗体可用靶标/标记/种属组合生成简短名称",
                        "category": "必须是 categories 中的一个值",
                        "brand": "品牌/厂家，优先归一化到 brands 中已有写法；无法归一时才返回新名称",
                        "catalog_no": "货号、目录号、Cat No.",
                        "amount": "单件规格数字，例如 100、500、1",
                        "amount_unit": "规格单位，例如 uL、mL、mg",
                        "quantity": "采购或入库数量，没有则 null",
                        "price": "单价或总价数字，不确定则 null",
                        "reason": "订购用途/备注，适合订购登记",
                        "note": "入库备注，适合试剂入库",
                        "is_antibody": "如果类型属于抗体则为 true",
                        "antibody": "只有 is_antibody 为 true 时填写抗体元数据字段",
                        "antibody.conjugate": "只填抗体本身实际偶联标记；未偶联/Unconjugated/Purified 一抗填 Unlabeled；二抗填 HRP、AF488 等实际标记；不要填 Indirect",
                    },
                },
                ensure_ascii=False,
            ),
        },
    ]


def _request_qwen(prompt: str) -> str:
    if not config.QWEN_API_KEY:
        raise ApiError(503, "Qwen API Key 未配置")
    try:
        import httpx
    except ImportError as exc:
        raise ApiError(503, "缺少 httpx 依赖，无法调用 Qwen") from exc
    payload = {
        "model": config.QWEN_MODEL,
        "input": prompt,
        "enable_thinking": False,
        "tools": [
            {"type": "web_search"},
        ],
        "tool_choice": "required",
    }
    url = f"{config.QWEN_BASE_URL}/responses"
    headers = {"Authorization": f"Bearer {config.QWEN_API_KEY}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=config.QWEN_TIMEOUT_SECONDS) as client:
            response = client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ApiError(504, "Qwen 联网搜索请求超时") from exc
    except httpx.HTTPError as exc:
        logger.warning("Qwen 联网搜索请求失败：%s", exc)
        raise ApiError(502, "Qwen 联网搜索请求失败") from exc
    if response.status_code >= 400:
        logger.warning("Qwen 返回错误状态：%s", response.status_code)
        raise ApiError(502, f"Qwen 返回错误：{response.status_code}")
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("output_text"):
            return str(data["output_text"])
        for item in data.get("output", []) if isinstance(data, dict) else []:
            if item.get("type") != "message":
                continue
            texts = []
            for part in item.get("content", []) or []:
                if part.get("type") in {"output_text", "text"} and part.get("text"):
                    texts.append(str(part["text"]))
            if texts:
                return "\n".join(texts)
        raise KeyError("output_text")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ApiError(502, "Qwen 响应格式不正确") from exc


def _normalize_extraction(data: dict[str, Any], allowed_categories: list[str]) -> dict[str, Any]:
    raw_category = _clean_text(data.get("category"), 80)
    antibody_raw = data.get("antibody") if isinstance(data.get("antibody"), dict) else {}
    antibody = {field: _clean_text(antibody_raw.get(field), TEXT_LIMITS.get(field, 240)) for field in METADATA_FIELDS}
    antibody["conjugate"] = _normalize_antibody_conjugate(
        antibody.get("conjugate"),
        data.get("name"),
        antibody.get("aliases"),
        antibody.get("raw_note"),
    )
    antibody_category = next((item for item in allowed_categories if item == "抗体"), "")
    is_antibody = bool(data.get("is_antibody")) or raw_category.lower() in {"antibody", "anti-body"} or any(antibody.values())
    category = raw_category if raw_category in allowed_categories else ""
    if is_antibody and antibody_category:
        category = antibody_category
    if not category and "其他" in allowed_categories:
        category = "其他"
    elif not category and allowed_categories:
        category = allowed_categories[0]
    item = {
        "name": _clean_text(data.get("name"), 200),
        "category": category,
        "brand": _clean_text(data.get("brand"), 160),
        "catalog_no": _clean_text(data.get("catalog_no"), 160),
        "amount": _clean_number(data.get("amount")),
        "amount_unit": _clean_text(data.get("amount_unit"), 40),
        "quantity": _clean_number(data.get("quantity")),
        "price": _clean_number(data.get("price")),
        "reason": _clean_text(data.get("reason"), 800),
        "note": _clean_text(data.get("note"), 800),
    }
    is_antibody = is_antibody or category == antibody_category
    return {
        "item": item,
        "is_antibody": is_antibody,
        "antibody": antibody,
        "confidence": _clean_confidence(data.get("confidence")),
        "warnings": _clean_warnings(data.get("warnings")),
        "model": config.QWEN_MODEL,
        "source": "qwen_web_search",
    }


def extract_reagent_fields(data: dict[str, Any]) -> dict[str, Any]:
    text = _clean_text(data.get("text"), 4000)
    if not text:
        raise ApiError(400, "请输入试剂链接或描述")
    allowed_categories = _clean_options(data.get("categories"), 80)
    messages = _extract_messages(data)
    content = _request_qwen("\n\n".join(message["content"] for message in messages))
    return _normalize_extraction(_parse_json_object(content), allowed_categories)
