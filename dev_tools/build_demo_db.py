from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCHEMA_PATH = ROOT / "db" / "schema.sql"
DEMO_DB_PATH = ROOT / "dev_tools" / "demo.sqlite3"

# This script is a local demo-data builder. Keep it isolated from production
# config so it can rebuild dev_tools/demo.sqlite3 from any checkout state.
os.environ["LABKEEPER_ENV"] = "development"
sys.path.insert(0, str(BACKEND))

from services.auth import hash_password  # noqa: E402

PHYSICAL_STATUSES = {"可用", "停用"}
BULK_REAGENT_COUNT = 220
BULK_SAMPLE_GROUP_COUNT = 120
BULK_ORDER_COUNT = 80


def main() -> None:
    remove_sqlite_files(DEMO_DB_PATH)
    DEMO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DEMO_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        seed(conn)
        assert_integrity(conn)
    print(f"Demo database written: {DEMO_DB_PATH}")


def remove_sqlite_files(path: Path) -> None:
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists():
            candidate.unlink()


def seed(conn: sqlite3.Connection) -> None:
    now = "2026-06-13 09:00:00"
    seed_users(conn, now)
    storage_dims = seed_storage(conn, now)
    positions = PositionAllocator(storage_dims)
    reagent_ids = seed_reagents(conn, positions, now)
    sample_ids = seed_samples(conn, positions, now)
    order_ids = seed_orders(conn, now)
    seed_arrivals(conn, order_ids, reagent_ids)
    seed_validations(conn, now)
    seed_movements(conn, now, reagent_ids, sample_ids)
    seed_audit_logs(conn, now)
    conn.commit()


def stamp(day: str, time_text: str = "09:00:00") -> str:
    return f"{day} {time_text}"


def coord_options(rows: int, cols: int) -> list[str]:
    coords: list[str] = []
    for row in range(rows):
        row_label = chr(ord("A") + row)
        for col in range(1, cols + 1):
            coords.append(f"{row_label}{col}")
    return coords


class PositionAllocator:
    def __init__(self, storage_dims: dict[int, tuple[int, int]]) -> None:
        self.storage_dims = storage_dims
        self.offsets: dict[int, int] = {}

    def next(self, node_id: int | None) -> str | None:
        if not node_id:
            return None
        rows, cols = self.storage_dims.get(node_id, (1, 1))
        coords = coord_options(rows, cols)
        offset = self.offsets.get(node_id, 0)
        if offset >= len(coords):
            return None
        self.offsets[node_id] = offset + 1
        return coords[offset]


def seed_users(conn: sqlite3.Connection, now: str) -> None:
    conn.execute(
        """
        INSERT INTO users (id, username, display_name, password_hash, role, permissions, is_active, created_at, updated_at)
        VALUES (1, 'admin', '管理员', ?, 'admin', NULL, 1, ?, ?)
        """,
        (hash_password("admin123"), now, now),
    )
    conn.executemany(
        """
        INSERT INTO users (id, username, display_name, password_hash, role, permissions, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'user', ?, ?, ?, ?)
        """,
        [
            (
                2,
                "demo_user",
                "测试用户",
                hash_password("demo123"),
                '{"inventory.manage":true,"location.manage":false,"inventory.search":true}',
                1,
                now,
                now,
            ),
            (
                3,
                "purchase",
                "采购助理",
                hash_password("demo123"),
                '{"inventory.manage":false,"location.manage":false,"inventory.search":true}',
                1,
                now,
                now,
            ),
            (
                4,
                "viewer",
                "只读观察员",
                hash_password("demo123"),
                '{"inventory.manage":false,"location.manage":false,"inventory.search":true}',
                1,
                now,
                now,
            ),
        ],
    )


def seed_storage(conn: sqlite3.Connection, now: str) -> dict[int, tuple[int, int]]:
    storage_nodes = [
        (1, None, "研究所", "space", "LAB", 2, 3, None, None, "Demo 根空间", 0),
        (2, 1, "负80冰箱A", "space", "FZ-A", 3, 3, 1, 1, "抗体、细胞因子和常用标本", 10),
        (3, 2, "A-第一层抽屉", "space", "FZ-A-D1", 2, 3, 1, 1, "高频使用盒", 10),
        (4, 3, "抗体盒-001", "box", "AB-001", 9, 9, 1, 1, "流式抗体", 10),
        (5, 3, "样本盒-001", "box", "SMP-001", 9, 9, 1, 2, "血清、血浆和灌洗液", 20),
        (6, 3, "细胞因子盒-001", "box", "CYT-001", 9, 9, 1, 3, "重组因子和刺激物", 30),
        (7, 2, "A-第二层抽屉", "space", "FZ-A-D2", 2, 3, 1, 2, "低频样本", 20),
        (8, 7, "样本盒-002", "box", "SMP-002", 9, 9, 1, 1, "全血和细胞悬液", 10),
        (9, 7, "组织盒-001", "box", "TIS-001", 9, 9, 1, 2, "组织和匀浆", 20),
        (10, 1, "负80冰箱B", "space", "FZ-B", 3, 3, 1, 2, "备用与长期冻存", 20),
        (11, 10, "B-第一层抽屉", "space", "FZ-B-D1", 2, 3, 1, 1, "备用样本盒", 10),
        (12, 11, "备用样本盒-003", "box", "SMP-003", 9, 9, 1, 1, "项目备份样本", 10),
        (13, 1, "4度冰箱", "space", "FRIDGE-4C", 2, 3, 2, 1, "短期试剂和缓冲液", 30),
        (14, 13, "4度门架", "space", "4C-RACK", 2, 4, 1, 1, "常用缓冲液", 10),
        (15, 14, "酶和缓冲液盒-001", "box", "ENZ-001", 5, 5, 1, 1, "酶、抑制剂、缓冲液", 10),
        (16, 14, "短期试剂盒-001", "box", "TMP-001", 5, 5, 1, 2, "短效期试剂", 20),
        (17, 1, "常温试剂柜", "space", "CAB-RT", 3, 4, 2, 2, "耗材和常温试剂盒", 40),
        (18, 17, "柜1层", "space", "CAB-RT-S1", 2, 5, 1, 1, "耗材和试剂盒", 10),
        (19, 18, "耗材格-001", "box", "CONS-001", 4, 6, 1, 1, "管、板、滤网", 10),
        (20, 18, "ELISA试剂盒区", "box", "KIT-001", 4, 6, 1, 2, "ELISA 和分子试剂盒", 20),
        (21, 1, "液氮罐", "space", "LN2", 2, 2, 2, 3, "细胞冻存", 50),
        (22, 21, "细胞冻存架A", "box", "LN2-RACK-A", 10, 10, 1, 1, "冻存细胞", 10),
        (23, 1, "待处理临时区", "space", "STAGING", 1, 4, 1, 3, "新到货和待归位", 60),
        (24, 23, "临时周转盒", "box", "STG-001", 4, 6, 1, 1, "短期周转", 10),
        (25, 11, "抗体盒-002", "box", "AB-002", 9, 9, 1, 2, "循环生成抗体", 20),
        (26, 11, "细胞因子盒-002", "box", "CYT-002", 9, 9, 1, 3, "循环生成细胞因子", 30),
        (27, 11, "试剂盒-002", "box", "KIT-002", 9, 9, 2, 1, "循环生成试剂盒", 40),
        (28, 14, "缓冲液盒-002", "box", "BUF-002", 5, 8, 1, 3, "循环生成缓冲液和酶", 30),
        (29, 14, "培养基盒-002", "box", "MED-002", 5, 8, 1, 4, "循环生成培养基和染料", 40),
        (30, 18, "耗材格-002", "box", "CONS-002", 4, 8, 1, 3, "循环生成耗材", 30),
        (31, 11, "样本盒-004", "box", "SMP-004", 9, 9, 2, 2, "循环生成标本", 50),
        (32, 11, "样本盒-005", "box", "SMP-005", 9, 9, 2, 3, "循环生成标本", 60),
        (33, 7, "样本盒-006", "box", "SMP-006", 9, 9, 1, 3, "循环生成标本", 30),
    ]
    conn.executemany(
        """
        INSERT INTO storage_nodes
            (id, parent_id, name, node_type, location_code, rows, cols, grid_row, grid_col, note, sort_order,
             created_by, updated_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        [(*node, now, now) for node in storage_nodes],
    )
    return {int(node[0]): (int(node[5] or 1), int(node[6] or 1)) for node in storage_nodes}


def seed_reagents(conn: sqlite3.Connection, positions: PositionAllocator, now: str) -> dict[str, int]:
    reagent_ids: dict[str, int] = {}
    next_id = 1

    def add(
        name: str,
        category: str,
        brand: str,
        catalog_no: str,
        amount: float | None,
        amount_unit: str,
        quantity: float,
        status: str,
        storage_node_id: int | None,
        entry_date: str,
        expiration_date: str | None,
        validation_status: str,
        note: str,
        count: int = 1,
    ) -> list[str]:
        nonlocal next_id
        source_code = f"RG{next_id:06d}"
        codes: list[str] = []
        for offset in range(count):
            reagent_id = next_id
            code = f"RG{reagent_id:06d}"
            placed_node_id = storage_node_id if status in PHYSICAL_STATUSES else None
            position = positions.next(placed_node_id)
            conn.execute(
                """
                INSERT INTO reagents
                    (id, code, source_code, aliquot_no, name, category, brand, catalog_no, amount, amount_unit, quantity,
                     status, storage_node_id, position_in_box, entry_date, expiration_date, validation_status, note,
                     created_by, updated_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (
                    reagent_id,
                    code,
                    source_code if count > 1 else code,
                    offset + 1 if count > 1 else None,
                    name,
                    category,
                    brand,
                    catalog_no,
                    amount,
                    amount_unit,
                    quantity,
                    status,
                    placed_node_id,
                    position,
                    entry_date,
                    expiration_date,
                    validation_status,
                    f"{note}；分装 {offset + 1}/{count}" if count > 1 else note,
                    stamp(entry_date),
                    now,
                ),
            )
            reagent_ids[code] = reagent_id
            codes.append(code)
            next_id += 1
        return codes

    add("Anti-CD45 抗体", "抗体", "BioLegend", "103101", 100, "uL", 1, "可用", 4, "2026-05-20", "2027-05-20", "通过", "Demo 验证通过抗体", 2)
    add("Anti-CD3e 抗体", "抗体", "BioLegend", "100201", 100, "uL", 1, "可用", 4, "2026-05-28", "2026-07-01", "待复核", "即将到期，需复核染色条件")
    add("Anti-CD4 抗体", "抗体", "BioLegend", "100401", 100, "uL", 1, "可用", 4, "2026-06-01", "2026-06-28", "未验证", "新批次未验证")
    add("Anti-CD8a 抗体", "抗体", "BioLegend", "100701", 100, "uL", 1, "可用", 4, "2026-06-01", "2027-02-10", "通过", "常用流式抗体")
    add("Anti-CD11b 抗体", "抗体", "BD Biosciences", "557396", 50, "uL", 1, "可用", 4, "2026-03-10", "2026-05-30", "待复核", "过期示例，仍保留实物")
    add("Anti-Ly6G 抗体", "抗体", "BioLegend", "127601", 100, "uL", 1, "可用", 4, "2026-04-18", "2027-04-18", "未验证", "粒细胞面板待验证")
    add("Anti-F4/80 抗体", "抗体", "BioLegend", "123107", 100, "uL", 1, "可用", 4, "2026-04-20", "2027-04-20", "通过", "巨噬细胞面板")
    add("Anti-CD19 抗体", "抗体", "BioLegend", "115507", 100, "uL", 1, "可用", 4, "2026-05-05", "2027-05-05", "通过", "B 细胞面板")
    add("Anti-Foxp3 抗体", "抗体", "Invitrogen", "17-5773-82", 50, "uL", 1, "停用", 4, "2025-12-01", "2026-06-20", "待复核", "停用但实物仍在盒内")
    add("Rabbit IgG 同型对照", "抗体", "CST", "3900", 100, "uL", 1, "可用", 4, "2026-05-08", "2027-05-08", "通过", "阴性对照")

    add("Recombinant Mouse IL-4", "细胞因子", "PeproTech", "214-14", 10, "ug", 1, "可用", 6, "2026-05-15", "2027-05-15", "未验证", "Th2 诱导")
    add("Recombinant Mouse GM-CSF", "细胞因子", "R&D Systems", "415-ML", 10, "ug", 1, "可用", 6, "2026-05-16", "2027-05-16", "通过", "骨髓细胞诱导", 2)
    add("Recombinant Mouse IL-33", "细胞因子", "BioLegend", "580508", 25, "ug", 1, "可用", 6, "2026-04-12", "2026-06-18", "未验证", "即将到期")
    add("Recombinant TNF-alpha", "细胞因子", "PeproTech", "315-01A", 10, "ug", 1, "可用", 6, "2026-03-22", "2027-03-22", "通过", "炎症刺激")
    add("Recombinant Mouse M-CSF", "细胞因子", "R&D Systems", "416-ML", 10, "ug", 1, "可用", 6, "2026-04-01", "2027-04-01", "未验证", "巨噬细胞诱导")

    add("PBS 缓冲液", "缓冲液", "Thermo Fisher", "10010023", 500, "mL", 1, "可用", 15, "2026-06-01", "2026-09-01", "未验证", "短期存放")
    add("FACS Buffer", "缓冲液", "BD Biosciences", "554657", 100, "mL", 1, "可用", 15, "2026-06-04", "2026-07-10", "通过", "含 BSA 和 EDTA")
    add("RIPA 裂解液", "缓冲液", "碧云天", "P0013B", 100, "mL", 1, "可用", 15, "2026-04-18", "2026-06-25", "未验证", "WB 裂解")
    add("Triton X-100", "缓冲液", "Sigma-Aldrich", "T8787", 100, "mL", 1, "停用", 15, "2025-11-08", "2027-11-08", "通过", "旧瓶停用，仍有实物")
    add("BSA", "其他", "Sigma-Aldrich", "A7030", 5, "g", 1, "可用", 15, "2026-05-01", "2027-05-01", "未验证", "封闭和缓冲液添加")
    add("DNase I", "酶", "Roche", "10104159001", 100, "mg", 1, "可用", 15, "2026-05-25", "2027-05-25", "通过", "组织消化")
    add("Collagenase IV", "酶", "Worthington", "LS004188", 100, "mg", 1, "可用", 15, "2026-05-25", "2027-05-25", "通过", "组织消化")
    add("Proteinase K", "酶", "Thermo Fisher", "EO0491", 100, "mg", 1, "可用", 15, "2026-05-28", "2027-05-28", "未验证", "核酸提取")
    add("Trypsin-EDTA", "酶", "Gibco", "25200056", 100, "mL", 1, "可用", 16, "2026-06-08", "2026-07-08", "未验证", "细胞传代短效期")
    add("Penicillin-Streptomycin", "培养基", "Gibco", "15140122", 100, "mL", 1, "可用", 16, "2026-06-08", "2026-07-08", "通过", "培养基添加")
    add("DMEM 高糖培养基", "培养基", "Gibco", "11965092", 500, "mL", 2, "可用", 16, "2026-06-10", "2026-08-10", "未验证", "细胞培养")
    add("胎牛血清 FBS", "培养基", "Gibco", "10099141", 500, "mL", 1, "可用", 16, "2026-06-10", "2027-06-10", "通过", "批次已测试")

    add("Mouse IL-5 ELISA Kit", "试剂盒", "R&D Systems", "DY405", 1, "kit", 1, "可用", 20, "2026-05-18", "2026-11-18", "通过", "细胞因子检测")
    add("Human IL-13 ELISA Kit", "试剂盒", "R&D Systems", "DY213", 1, "kit", 1, "可用", 20, "2026-05-18", "2026-11-18", "未验证", "待做标准曲线")
    add("RNA 提取试剂盒", "试剂盒", "翌圣生物", "19221ES50", 1, "kit", 1, "可用", 20, "2026-04-30", "2026-10-30", "通过", "Demo 分子实验")
    add("cDNA 反转录试剂盒", "试剂盒", "翌圣生物", "11141ES60", 1, "kit", 1, "可用", 20, "2026-05-02", "2026-10-30", "通过", "qPCR 前处理")
    add("qPCR SYBR Mix", "试剂盒", "翌圣生物", "11201ES08", 1, "kit", 1, "可用", 20, "2026-05-02", "2026-10-30", "通过", "qPCR")
    add("BCA 蛋白定量试剂盒", "试剂盒", "碧云天", "P0012", 1, "kit", 1, "可用", 20, "2026-05-10", "2026-12-10", "未验证", "WB 前定量")

    add("DAPI 染色液", "染料", "Invitrogen", "D1306", 1, "mg", 1, "可用", 16, "2026-06-05", "2027-06-05", "通过", "细胞核染色")
    add("Propidium Iodide", "染料", "Sigma-Aldrich", "P4170", 1, "mg", 1, "可用", 16, "2026-05-30", "2027-05-30", "通过", "死细胞染色")
    add("Annexin V-FITC", "染料", "BD Biosciences", "556419", 100, "test", 1, "可用", 16, "2026-05-30", "2026-06-22", "待复核", "凋亡检测，即将到期")
    add("Trypan Blue", "染料", "Gibco", "15250061", 100, "mL", 1, "可用", 16, "2026-03-01", "2027-03-01", "通过", "细胞计数")
    add("SYBR Green I", "染料", "Invitrogen", "S7563", 500, "uL", 1, "已耗尽", None, "2025-11-11", "2026-11-11", "通过", "已耗尽示例")

    add("96孔透明板", "耗材", "Corning", "3599", 50, "个", 50, "可用", 19, "2026-05-24", None, "未验证", "ELISA 和细胞实验")
    add("15mL 离心管", "耗材", "Corning", "430052", 50, "个", 50, "可用", 19, "2026-05-24", None, "未验证", "常用耗材")
    add("50mL 离心管", "耗材", "Corning", "430828", 25, "个", 25, "可用", 19, "2026-05-24", None, "未验证", "常用耗材")
    add("70um 细胞滤网", "耗材", "Corning", "352350", 50, "个", 50, "可用", 19, "2026-05-24", None, "未验证", "组织消化过滤")
    add("200uL 枪头盒", "耗材", "Axygen", "T-200-Y", 10, "盒", 10, "可用", 19, "2026-05-24", None, "未验证", "移液耗材")
    add("ELISA 试剂盒旧批次", "试剂盒", "R&D Systems", "DY210-OLD", 1, "kit", 1, "停用", None, "2026-01-12", "2026-07-12", "待复核", "未归位停用示例")
    add("红细胞裂解液", "缓冲液", "索莱宝", "R1010", 100, "mL", 1, "可用", None, "2026-06-12", "2027-06-12", "未验证", "新到货，尚未归位")

    generated_templates = [
        ("Demo 抗体", "抗体", "BioLegend", "DAB", 100, "uL", 1, [4, 25]),
        ("Demo 细胞因子", "细胞因子", "R&D Systems", "DCYT", 10, "ug", 1, [6, 26]),
        ("Demo 缓冲液", "缓冲液", "Thermo Fisher", "DBUF", 500, "mL", 1, [28, 15, 28]),
        ("Demo 酶", "酶", "翌圣生物", "DENZ", 100, "mg", 1, [28, 15, 28]),
        ("Demo 培养基", "培养基", "Gibco", "DMED", 500, "mL", 1, [29, 16, 29]),
        ("Demo 染料", "染料", "Invitrogen", "DDYE", 1, "mg", 1, [29, 16, 29]),
        ("Demo 试剂盒", "试剂盒", "R&D Systems", "DKIT", 1, "kit", 1, [27, 20, 27]),
        ("Demo 耗材", "耗材", "Corning", "DCON", 50, "个", 50, [30, 19, 30]),
        ("Demo 其他试剂", "其他", "Sigma-Aldrich", "DMIX", 1, "kit", 1, [24, 27, 30]),
    ]
    validation_cycle = ["未验证", "通过", "待复核", "通过", "未验证"]
    for index in range(1, BULK_REAGENT_COUNT + 1):
        base_name, category, brand, catalog_prefix, amount, amount_unit, quantity, target_nodes = generated_templates[(index - 1) % len(generated_templates)]
        status = "已耗尽" if index % 31 == 0 else ("停用" if index % 17 == 0 else "可用")
        storage_node_id = target_nodes[index % len(target_nodes)]
        if index % 23 == 0 and status == "可用":
            storage_node_id = None
        if category == "耗材":
            expiration_date = None if index % 5 else "2027-12-31"
        elif index % 19 == 0:
            expiration_date = "2026-05-25"
        elif index % 13 == 0:
            expiration_date = "2026-06-20"
        elif index % 7 == 0:
            expiration_date = "2026-07-05"
        else:
            expiration_date = f"2027-{(index % 12) + 1:02d}-{(index % 24) + 1:02d}"
        validation_status = validation_cycle[index % len(validation_cycle)]
        if category == "抗体" and index % 4 == 0:
            validation_status = "未验证"
        add(
            f"{base_name} {index}",
            category,
            brand,
            f"{catalog_prefix}-{index:03d}",
            amount,
            amount_unit,
            quantity,
            status,
            storage_node_id,
            f"2026-06-{(index % 13) + 1:02d}",
            expiration_date,
            validation_status,
            f"循环生成 Demo 试剂 {index}",
        )

    return reagent_ids


def seed_samples(conn: sqlite3.Connection, positions: PositionAllocator, now: str) -> dict[str, int]:
    sample_ids: dict[str, int] = {}
    next_id = 1

    def add_group(
        name: str,
        category: str,
        count: int,
        amount: float,
        amount_unit: str,
        status: str,
        storage_node_id: int | None,
        entry_date: str,
        note: str,
    ) -> None:
        nonlocal next_id
        source_code = f"SP{next_id:06d}"
        for offset in range(count):
            sample_id = next_id
            code = f"SP{sample_id:06d}"
            placed_node_id = storage_node_id if status in PHYSICAL_STATUSES else None
            position = positions.next(placed_node_id)
            conn.execute(
                """
                INSERT INTO clinical_samples
                    (id, code, source_code, aliquot_no, name, category, amount, amount_unit, quantity, status,
                     storage_node_id, position_in_box, entry_date, expiration_date, validation_status, note,
                     created_by, updated_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, NULL, '', ?, 1, 1, ?, ?)
                """,
                (
                    sample_id,
                    code,
                    source_code,
                    offset + 1,
                    name,
                    category,
                    amount,
                    amount_unit,
                    status,
                    placed_node_id,
                    position,
                    entry_date,
                    f"{note}；冻存管 {offset + 1}/{count}",
                    stamp(entry_date),
                    now,
                ),
            )
            sample_ids[code] = sample_id
            next_id += 1

    add_group("SMP-001", "血清", 3, 200, "uL", "可用", 5, "2026-06-02", "Demo 血清样本")
    add_group("SMP-002", "灌洗液", 4, 500, "uL", "可用", 5, "2026-06-05", "BALF 分装")
    add_group("SMP-003", "血浆", 2, 250, "uL", "可用", 5, "2026-06-06", "血浆备份")
    add_group("SMP-004", "全血", 2, 1, "mL", "可用", 8, "2026-06-07", "全血样本")
    add_group("SMP-005", "细胞悬液", 4, 1, "mL", "可用", 8, "2026-06-08", "PBMC 细胞悬液")
    add_group("SMP-006", "组织", 3, 80, "mg", "可用", 9, "2026-06-09", "肺组织")
    add_group("SMP-007", "尿液", 2, 500, "uL", "可用", 12, "2026-06-09", "尿液样本")
    add_group("SMP-008", "灌洗液", 4, 500, "uL", "可用", 12, "2026-06-10", "备份 BALF")
    add_group("SMP-009", "细胞", 6, 1, "mL", "可用", 22, "2026-06-11", "冻存细胞")
    add_group("SMP-010", "匀浆", 2, 300, "uL", "可用", 9, "2026-06-11", "组织匀浆")
    add_group("SMP-011", "血清", 3, 200, "uL", "可用", 5, "2026-06-12", "随访血清")
    add_group("SMP-012", "组织", 3, 70, "mg", "可用", 9, "2026-06-12", "组织复测")
    add_group("SMP-013", "血浆", 2, 250, "uL", "停用", 8, "2026-05-18", "停用但仍有实体管")
    add_group("SMP-014", "灌洗液", 2, 500, "uL", "可用", None, "2026-06-13", "新入库未归位")
    add_group("SMP-015", "细胞", 2, 1, "mL", "已耗尽", None, "2026-05-01", "已出库耗尽示例")

    sample_templates = [
        ("Demo 血清", "血清", 200, "uL", [31, 5, 32, 33]),
        ("Demo 血浆", "血浆", 250, "uL", [31, 8, 32, 33]),
        ("Demo 灌洗液", "灌洗液", 500, "uL", [31, 12, 32, 33]),
        ("Demo 组织", "组织", 80, "mg", [31, 9, 32, 33]),
        ("Demo 细胞", "细胞", 1, "mL", [31, 22, 32, 33]),
        ("Demo 尿液", "尿液", 500, "uL", [31, 12, 32, 33]),
        ("Demo 匀浆", "匀浆", 300, "uL", [31, 9, 32, 33]),
    ]
    for index in range(1, BULK_SAMPLE_GROUP_COUNT + 1):
        base_name, category, amount, amount_unit, target_nodes = sample_templates[(index - 1) % len(sample_templates)]
        tube_count = 1 + (index % 3)
        status = "已耗尽" if index % 41 == 0 else ("停用" if index % 29 == 0 else "可用")
        storage_node_id = target_nodes[index % len(target_nodes)]
        if index % 37 == 0 and status == "可用":
            storage_node_id = None
        add_group(
            f"{base_name} {index}",
            category,
            tube_count,
            amount,
            amount_unit,
            status,
            storage_node_id,
            f"2026-06-{(index % 13) + 1:02d}",
            f"循环生成 Demo 标本 {index}",
        )

    return sample_ids


def seed_orders(conn: sqlite3.Connection, now: str) -> dict[str, int]:
    orders = [
        ("anti_cd45", 1, "Anti-CD45 抗体", "抗体", "BioLegend", "103101", 100, "uL", 2, "流式面板补货", 3600, "已订购", "2026-05-18 09:00:00", "2026-05-20 09:30:00"),
        ("pbs", 1, "PBS 缓冲液", "缓冲液", "Thermo Fisher", "10010023", 500, "mL", 1, "常规补货", 260, "已订购", "2026-05-28 10:00:00", "2026-06-01 11:00:00"),
        ("anti_cd3", 2, "Anti-CD3e 抗体", "抗体", "BioLegend", "100201", 100, "uL", 1, "T 细胞面板", 1800, "已订购", "2026-05-26 14:30:00", "2026-05-28 11:00:00"),
        ("gmcsf", 2, "Recombinant Mouse GM-CSF", "细胞因子", "R&D Systems", "415-ML", 10, "ug", 2, "诱导实验", 4200, "已订购", "2026-05-14 09:20:00", "2026-05-16 10:10:00"),
        ("il5_elisa", 1, "Mouse IL-5 ELISA Kit", "试剂盒", "R&D Systems", "DY405", 1, "kit", 1, "细胞因子检测", 3600, "已订购", "2026-05-15 16:00:00", "2026-05-18 15:00:00"),
        ("plates", 3, "96孔透明板", "耗材", "Corning", "3599", 50, "个", 1, "ELISA 耗材", 520, "已订购", "2026-05-22 09:10:00", "2026-05-24 13:00:00"),
        ("dapi", 2, "DAPI 染色液", "染料", "Invitrogen", "D1306", 1, "mg", 1, "成像染色", 980, "已订购", "2026-06-02 09:00:00", "2026-06-05 10:20:00"),
        ("rna_kit", 1, "RNA 提取试剂盒", "试剂盒", "翌圣生物", "19221ES50", 1, "kit", 1, "qPCR 项目", 1200, "已订购", "2026-04-28 09:00:00", "2026-04-30 10:00:00"),
        ("anti_cd25", 1, "Anti-CD25 抗体", "抗体", "BioLegend", "102005", 100, "uL", 1, "Treg 面板补齐", 1900, "已订购", "2026-06-12 09:30:00", now),
        ("fix_perm", 2, "Foxp3 Fix/Perm Buffer Set", "试剂盒", "Invitrogen", "00-5523-00", 1, "kit", 1, "Foxp3 染色", 2400, "已订购", "2026-06-11 15:10:00", now),
        ("tubes", 3, "1.5mL EP 管", "耗材", "Axygen", "MCT-150-C", 500, "个", 2, "耗材补货", 180, "已订购", "2026-06-10 10:30:00", now),
        ("il17_elisa", 1, "Mouse IL-17A ELISA Kit", "试剂盒", "R&D Systems", "DY421", 1, "kit", 1, "待开展检测", 3600, "已订购", "2026-06-09 11:20:00", now),
        ("matrigel", 2, "Matrigel Matrix", "其他", "Corning", "354234", 10, "mL", 1, "类器官实验", 5300, "已订购", "2026-06-08 09:45:00", now),
        ("seahorse", 1, "Seahorse XF Assay Medium", "培养基", "Agilent", "103575-100", 500, "mL", 1, "代谢实验", 980, "已订购", "2026-06-07 16:00:00", now),
        ("old_order", 1, "旧项目抗体", "抗体", "Abcam", "ab-old", 100, "uL", 1, "项目取消", 1600, "停用", "2026-05-01 09:00:00", "2026-05-03 09:00:00"),
    ]
    order_ids: dict[str, int] = {}
    for order_id, row in enumerate(orders, start=1):
        key, requester_id, name, category, brand, catalog_no, amount, amount_unit, quantity, reason, price, status, created_at, updated_at = row
        conn.execute(
            """
            INSERT INTO orders
                (id, requester_id, name, category, brand, catalog_no, amount, amount_unit, quantity, reason, price, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (order_id, requester_id, name, category, brand, catalog_no, amount, amount_unit, quantity, reason, price, status, created_at, updated_at),
        )
        order_ids[key] = order_id
    next_id = len(orders) + 1
    order_templates = [
        ("Demo 订购抗体", "抗体", "BioLegend", "ORD-AB", 100, "uL", 1, "流式面板备货", 1800),
        ("Demo 订购细胞因子", "细胞因子", "R&D Systems", "ORD-CYT", 10, "ug", 1, "刺激实验备货", 2200),
        ("Demo 订购缓冲液", "缓冲液", "Thermo Fisher", "ORD-BUF", 500, "mL", 1, "缓冲液补货", 260),
        ("Demo 订购试剂盒", "试剂盒", "翌圣生物", "ORD-KIT", 1, "kit", 1, "检测项目备货", 1300),
        ("Demo 订购耗材", "耗材", "Corning", "ORD-CON", 50, "个", 2, "耗材补货", 520),
        ("Demo 订购培养基", "培养基", "Gibco", "ORD-MED", 500, "mL", 1, "细胞培养备货", 480),
    ]
    for index in range(1, BULK_ORDER_COUNT + 1):
        name, category, brand, catalog_prefix, amount, amount_unit, quantity, reason, price = order_templates[(index - 1) % len(order_templates)]
        status = "停用" if index % 29 == 0 else "已订购"
        created_at = f"2026-06-{(index % 13) + 1:02d} {(8 + index % 9):02d}:{(index * 7) % 60:02d}:00"
        order_id = next_id
        conn.execute(
            """
            INSERT INTO orders
                (id, requester_id, name, category, brand, catalog_no, amount, amount_unit, quantity, reason, price, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                1 + (index % 3),
                f"{name} {index}",
                category,
                brand,
                f"{catalog_prefix}-{index:03d}",
                amount,
                amount_unit,
                quantity,
                f"{reason} {index}",
                price,
                status,
                created_at,
                now,
            ),
        )
        order_ids[f"bulk_order_{index:03d}"] = order_id
        next_id += 1
    return order_ids


def storage_snapshot(conn: sqlite3.Connection, node_id: int | None, position: str | None = None) -> str:
    if not node_id:
        return "未归位"
    names: list[str] = []
    current = conn.execute("SELECT id, parent_id, name FROM storage_nodes WHERE id = ?", (node_id,)).fetchone()
    guard = 0
    while current is not None and guard < 100:
        names.append(str(current["name"]))
        parent_id = current["parent_id"]
        current = conn.execute("SELECT id, parent_id, name FROM storage_nodes WHERE id = ?", (parent_id,)).fetchone() if parent_id else None
        guard += 1
    path = " / ".join(reversed(names))
    return f"{path} / {position}" if position else path


def seed_arrivals(conn: sqlite3.Connection, order_ids: dict[str, int], reagent_ids: dict[str, int]) -> None:
    arrivals = [
        ("anti_cd45", "2026-05-20", "2027-05-20", "Demo 到货：抗体两支分装"),
        ("pbs", "2026-06-01", "2026-09-01", "Demo 到货：短期缓冲液"),
        ("anti_cd3", "2026-05-28", "2026-07-01", "Demo 到货：即将到期抗体"),
        ("gmcsf", "2026-05-16", "2027-05-16", "Demo 到货：细胞因子两管"),
        ("il5_elisa", "2026-05-18", "2026-11-18", "Demo 到货：ELISA 试剂盒"),
        ("plates", "2026-05-24", None, "Demo 到货：耗材"),
        ("dapi", "2026-06-05", "2027-06-05", "Demo 到货：染料"),
        ("rna_kit", "2026-04-30", "2026-10-30", "Demo 到货：分子试剂盒"),
    ]
    for order_key, entry_date, expiration_date, note in arrivals:
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_ids[order_key],)).fetchone()
        if order is None:
            continue
        reagent_rows = conn.execute(
            """
            SELECT id, storage_node_id, position_in_box
            FROM reagents
            WHERE catalog_no = ?
            ORDER BY id
            LIMIT ?
            """,
            (order["catalog_no"], int(order["quantity"] or 1)),
        ).fetchall()
        for item in reagent_rows:
            reagent_id = int(item["id"])
            item = conn.execute("SELECT storage_node_id, position_in_box FROM reagents WHERE id = ?", (reagent_id,)).fetchone()
            node_id = item["storage_node_id"] if item else None
            position = item["position_in_box"] if item else None
            conn.execute(
                """
                INSERT INTO arrivals
                    (order_id, item_type, item_id, entry_date, received_by, storage_node_id, position_in_box,
                     location_snapshot, expiration_date, note, created_at)
                VALUES (?, 'reagent', ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_ids[order_key],
                    reagent_id,
                    entry_date,
                    node_id,
                    position,
                    storage_snapshot(conn, node_id, position),
                    expiration_date,
                    note,
                    stamp(entry_date, "10:00:00"),
                ),
            )


def seed_validations(conn: sqlite3.Connection, now: str) -> None:
    validations = [
        ("103101", 1, "2026-05-21", "流式", "通过", "CD45 门控清晰，作为 Demo 通过记录。"),
        ("100201", 1, "2026-05-29", "流式", "待复核", "CD3 背景略高，建议复测滴度。"),
        ("100701", 2, "2026-06-02", "流式", "通过", "CD8a 信号稳定。"),
        ("557396", 2, "2026-04-01", "流式", "待复核", "过期前后需复核。"),
        ("123107", 1, "2026-05-02", "流式", "通过", "F4/80 染色稳定。"),
        ("115507", 1, "2026-05-08", "流式", "通过", "CD19 阳性群清晰。"),
        ("415-ML", 2, "2026-05-17", "细胞培养", "通过", "诱导效果符合预期。"),
        ("554657", 2, "2026-06-05", "流式", "通过", "FACS Buffer 批次可用。"),
        ("DY405", 1, "2026-05-19", "ELISA", "通过", "标准曲线 R2 > 0.99。"),
        ("DY213", 1, "2026-05-22", "ELISA", "待复核", "待补标准曲线。"),
        ("19221ES50", 1, "2026-05-01", "qPCR", "通过", "RNA 纯度合格。"),
        ("11141ES60", 1, "2026-05-03", "qPCR", "通过", "反转录效率合格。"),
        ("556419", 2, "2026-06-01", "流式", "待复核", "Annexin V-FITC 临近效期。"),
    ]
    for validation_id, row in enumerate(validations, start=1):
        catalog_no, validator_id, validation_date, method, result, description = row
        conn.execute(
            """
            INSERT INTO validations
                (id, catalog_no, validator_id, validation_date, method, result, description, image_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)
            """,
            (validation_id, catalog_no, validator_id, validation_date, method, result, description, now),
        )


def seed_movements(
    conn: sqlite3.Connection,
    now: str,
    reagent_ids: dict[str, int],
    sample_ids: dict[str, int],
) -> None:
    movement_id = 1

    def add_movement(item_type: str, item_id: int, moved_at: str, reason: str, note: str = "") -> None:
        nonlocal movement_id
        table = "clinical_samples" if item_type == "sample" else "reagents"
        item = conn.execute(f"SELECT storage_node_id, position_in_box FROM {table} WHERE id = ?", (item_id,)).fetchone()
        if item is None or not item["storage_node_id"]:
            return
        conn.execute(
            """
            INSERT INTO movements
                (id, object_type, object_id, item_type, item_id, from_storage_node_id, from_position_in_box,
                 to_storage_node_id, to_position_in_box, from_location_snapshot, to_location_snapshot, moved_by, moved_at, reason, note)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, '未归位', ?, 1, ?, ?, ?)
            """,
            (
                movement_id,
                item_type,
                str(item_id),
                item_type,
                item_id,
                item["storage_node_id"],
                item["position_in_box"],
                storage_snapshot(conn, item["storage_node_id"], item["position_in_box"]),
                moved_at,
                reason,
                note,
            ),
        )
        movement_id += 1

    reagent_rows = conn.execute(
        """
        SELECT id, entry_date FROM reagents
        WHERE storage_node_id IS NOT NULL AND COALESCE(status, '') IN ('可用', '停用')
        ORDER BY id
        """
    ).fetchall()
    for row in reagent_rows:
        add_movement("reagent", int(row["id"]), stamp(row["entry_date"], "10:30:00"), "Demo 入库", "随 Demo 数据自动生成")

    sample_rows = conn.execute(
        """
        SELECT id, entry_date FROM clinical_samples
        WHERE storage_node_id IS NOT NULL AND status IN ('可用', '停用')
        ORDER BY id
        """
    ).fetchall()
    for row in sample_rows:
        add_movement("sample", int(row["id"]), stamp(row["entry_date"], "11:00:00"), "Demo 标本入库", "随 Demo 数据自动生成")

    # 额外保留几条高频操作记录，便于演示流转记录和详情页。
    extra_moves = [
        ("reagent", reagent_ids["RG000004"], "2026-06-03 16:20:00", "整理抗体盒", "从盒内前排调整到当前孔位"),
        ("reagent", reagent_ids["RG000048"], "2026-06-13 09:30:00", "新到货待归位", "暂未分配位置，特殊关注中可见"),
        ("sample", sample_ids["SP000040"], "2026-06-13 10:00:00", "新样本待归位", "暂存在待处理区外，未分配盒位"),
    ]
    for item_type, item_id, moved_at, reason, note in extra_moves:
        add_movement(item_type, item_id, moved_at, reason, note)


def seed_audit_logs(conn: sqlite3.Connection, now: str) -> None:
    conn.execute(
        """
        INSERT INTO audit_logs (user_id, action, target_table, target_id, new_value, created_at)
        VALUES (1, 'dev_seed_demo_database', 'database', NULL, '{"source":"dev_tools/build_demo_db.py","profile":"expanded"}', ?)
        """,
        (now,),
    )


def assert_integrity(conn: sqlite3.Connection) -> None:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    if not row or row[0] != "ok":
        raise RuntimeError("Demo database integrity check failed")


if __name__ == "__main__":
    main()
