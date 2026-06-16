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

SYSTEM_NOT_ORDERED_NODE_ID = -1
SYSTEM_NOT_ARRIVED_NODE_ID = -2
SYSTEM_UNPLACED_NODE_ID = -3
SYSTEM_CHECKED_OUT_NODE_ID = -4
SYSTEM_STORAGE_NODE_IDS = (
    SYSTEM_NOT_ORDERED_NODE_ID,
    SYSTEM_NOT_ARRIVED_NODE_ID,
    SYSTEM_UNPLACED_NODE_ID,
    SYSTEM_CHECKED_OUT_NODE_ID,
)
SYSTEM_STORAGE_NODE_LABELS = {
    SYSTEM_NOT_ORDERED_NODE_ID: "未订购",
    SYSTEM_NOT_ARRIVED_NODE_ID: "未到货",
    SYSTEM_UNPLACED_NODE_ID: "未归位",
    SYSTEM_CHECKED_OUT_NODE_ID: "已出库",
}

MOVEMENT_REASON_ORDER = "订购"
MOVEMENT_REASON_ARRIVAL = "到货入库"
MOVEMENT_REASON_REGISTER = "入库登记"
MOVEMENT_REASON_MOVE = "位置移动"
MOVEMENT_REASON_CHECKOUT = "出库"
MOVEMENT_REASON_ROLLBACK = "回滚移动"
MOVEMENT_REASON_STATUS = "状态调整"
MOVEMENT_REASON_SPACE_MOVE = "空间移动"
FIXED_MOVEMENT_REASONS = (
    MOVEMENT_REASON_ORDER,
    MOVEMENT_REASON_ARRIVAL,
    MOVEMENT_REASON_REGISTER,
    MOVEMENT_REASON_MOVE,
    MOVEMENT_REASON_CHECKOUT,
    MOVEMENT_REASON_ROLLBACK,
    MOVEMENT_REASON_STATUS,
    MOVEMENT_REASON_SPACE_MOVE,
)

PERMISSIONS = {
    "inventory.manage": "库存维护",
    "location.manage": "位置维护",
    "inventory.search": "明细搜索",
    "inventory.view_reagents": "查看试剂",
    "inventory.view_samples": "查看临床标本",
}

DEFAULT_USER_PERMISSIONS = {
    "inventory.manage": False,
    "location.manage": False,
    "inventory.search": True,
    "inventory.view_reagents": True,
    "inventory.view_samples": True,
}
