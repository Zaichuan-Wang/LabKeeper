"""空间网格计算核心逻辑测试。"""
from services.storage_inventory import (
    assign_grid_positions,
    coord_list,
    default_grid_for_node,
    grid_label,
    grid_position,
    clean_positive_int,
    clean_node_dimension,
    occupies_storage,
    reagent_is_consumed,
)


class TestGridLabel:
    def test_single_col(self):
        assert grid_label(1) == "1"
        assert grid_label(5) == "5"

    def test_with_cols(self):
        assert grid_label(1, 3) == "A1"
        assert grid_label(3, 3) == "A3"
        assert grid_label(4, 3) == "B1"
        assert grid_label(9, 3) == "C3"

    def test_large_row(self):
        assert grid_label(79, 3) == str(79)


class TestGridPosition:
    def test_with_row_col(self):
        assert grid_position(1, 1, 3, 99) == 1
        assert grid_position(2, 3, 5, 99) == 8

    def test_fallback(self):
        assert grid_position(None, None, 3, 7) == 7
        assert grid_position(0, 0, 3, 42) == 42


class TestAssignGridPositions:
    def test_manual_positions(self):
        items = [
            {"grid_row": 1, "grid_col": 1},
            {"grid_row": 1, "grid_col": 3},
        ]
        max_pos = assign_grid_positions(items, 3)
        assert items[0]["grid_label"] == "A1"
        assert items[1]["grid_label"] == "A3"
        assert max_pos == 3

    def test_fallback_positions(self):
        items = [{}, {}, {}]
        max_pos = assign_grid_positions(items, 3)
        assert items[0]["grid_label"] == "A1"
        assert items[1]["grid_label"] == "A2"
        assert items[2]["grid_label"] == "A3"
        assert max_pos == 3

    def test_conflict_avoidance(self):
        items = [
            {"grid_row": 1, "grid_col": 1},
            {},
        ]
        assign_grid_positions(items, 3)
        assert items[1]["grid_label"] == "A2"


class TestDefaultGridForNode:
    def test_explicit(self):
        assert default_grid_for_node("space", 3, 5) == (3, 5)

    def test_box_default(self):
        assert default_grid_for_node("box", None, None) == (9, 9)

    def test_space_default(self):
        assert default_grid_for_node("space", None, None) == (1, 1)


class TestCoordList:
    def test_basic(self):
        coords = coord_list(2, 3)
        assert coords == ["A1", "A2", "A3", "B1", "B2", "B3"]

    def test_single(self):
        assert coord_list(1, 1) == ["A1"]


class TestCleanPositiveInt:
    def test_valid(self):
        assert clean_positive_int(5) == 5
        assert clean_positive_int("3") == 3

    def test_invalid(self):
        assert clean_positive_int(0) is None
        assert clean_positive_int(-1) is None
        assert clean_positive_int("abc") is None

    def test_max(self):
        assert clean_positive_int(100, 50) == 50


class TestCleanNodeDimension:
    def test_box_rows_max(self):
        assert clean_node_dimension("box", "rows", 30) == 26

    def test_box_cols_max(self):
        assert clean_node_dimension("box", "cols", 60) == 50

    def test_space_max(self):
        assert clean_node_dimension("space", "rows", 60) == 50


class TestOccupiesStorage:
    def test_physical(self):
        assert occupies_storage("可用") is True
        assert occupies_storage("停用") is True

    def test_non_physical(self):
        assert occupies_storage("已耗尽") is False
        assert occupies_storage("已订购") is False
        assert occupies_storage("") is False
        assert occupies_storage(None) is False


class TestReagentIsConsumed:
    def test_consumed_status(self):
        assert reagent_is_consumed("已耗尽", 10) is True

    def test_zero_quantity(self):
        assert reagent_is_consumed("可用", 0) is True
        assert reagent_is_consumed("可用", "0") is True

    def test_normal(self):
        assert reagent_is_consumed("可用", 5) is False
        assert reagent_is_consumed("已订购", None) is False


def _seed_user(conn, user_id=1):
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, display_name, password_hash, role, is_active, created_at, updated_at) VALUES (?, 'test', '测试', 'x', 'admin', 1, '2025-01-01', '2025-01-01')",
        (user_id,),
    )
    conn.commit()


class TestNodePath:
    def test_node_full_path(self, patch_db):
        conn = patch_db
        _seed_user(conn)
        conn.execute(
            "INSERT INTO storage_nodes (id, parent_id, name, node_type, created_by, updated_by, created_at, updated_at) VALUES (1, NULL, '根', 'space', 1, 1, '2025-01-01', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO storage_nodes (id, parent_id, name, node_type, created_by, updated_by, created_at, updated_at) VALUES (2, 1, '冰箱A', 'space', 1, 1, '2025-01-01', '2025-01-01')"
        )
        conn.commit()
        from services.storage_inventory import node_full_path
        assert node_full_path(conn, 2) == "根 / 冰箱A"
        assert node_full_path(conn, 1) == "根"


class TestDescendantNodeIds:
    def test_basic(self, patch_db):
        conn = patch_db
        _seed_user(conn)
        conn.execute(
            "INSERT INTO storage_nodes (id, parent_id, name, node_type, created_by, updated_by, created_at, updated_at) VALUES (1, NULL, '根', 'space', 1, 1, '2025-01-01', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO storage_nodes (id, parent_id, name, node_type, created_by, updated_by, created_at, updated_at) VALUES (2, 1, '子', 'space', 1, 1, '2025-01-01', '2025-01-01')"
        )
        conn.execute(
            "INSERT INTO storage_nodes (id, parent_id, name, node_type, created_by, updated_by, created_at, updated_at) VALUES (3, 2, '孙', 'space', 1, 1, '2025-01-01', '2025-01-01')"
        )
        conn.commit()
        from services.storage_inventory import descendant_node_ids
        ids = descendant_node_ids(conn, 1, True)
        assert sorted(ids) == [1, 2, 3]
        ids_no_self = descendant_node_ids(conn, 1, False)
        assert sorted(ids_no_self) == [2, 3]
