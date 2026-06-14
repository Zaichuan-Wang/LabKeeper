from __future__ import annotations

ROLES = {"user": "普通用户", "admin": "管理员"}

STATUS_ORDERED = "已订购"
STATUS_AVAILABLE = "可用"
STATUS_DISABLED = "停用"
STATUS_CONSUMED = "已耗尽"
VALIDATION_UNVERIFIED = "未验证"

REAGENT_STATUSES = ("已订购", "可用", "停用", "已耗尽")
SAMPLE_STATUSES = ("可用", "停用", "已耗尽")
VALIDATION_STATUSES = ("未验证", "通过", "不通过", "待复核")
PHYSICAL_INVENTORY_STATUSES = ("可用", "停用")
PHYSICAL_INVENTORY_STATUS_SQL = "('可用', '停用')"

PERMISSIONS = {
    "inventory.manage": "库存维护",
    "location.manage": "位置维护",
    "inventory.search": "明细搜索",
}

DEFAULT_USER_PERMISSIONS = {
    "inventory.manage": True,
    "location.manage": False,
    "inventory.search": True,
}
