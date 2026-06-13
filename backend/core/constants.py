from __future__ import annotations

ROLES = {"user": "普通用户", "admin": "管理员"}

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

NODE_TYPE_LABELS = {
    "space": "普通空间",
    "box": "盒子",
}

BOX_SPECS = {"9x9": (9, 9), "9x12": (9, 12), "10x10": (10, 10), "8x12": (8, 12), "5x5": (5, 5)}
