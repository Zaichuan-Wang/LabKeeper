"""FastAPI 集成流程测试，使用临时 SQLite 数据库。"""


def api_ok(response, status_code=200):
    assert response.status_code == status_code, response.text
    return response.json()


def test_inventory_storage_and_permission_workflow(app_client, auth_headers):
    health = api_ok(app_client.get("/api/health"))
    assert health["ok"] is True
    assert app_client.get("/api/dashboard").status_code == 200

    dashboard = api_ok(app_client.get("/api/dashboard", headers=auth_headers))
    assert dashboard["metrics"]["total_inventory"] == 0

    tree = api_ok(app_client.get("/api/storage/tree", headers=auth_headers))
    roots = [item for item in tree["items"] if item.get("parent_id") is None]
    assert len(roots) == 1
    root_id = roots[0]["id"]

    freezer = api_ok(
        app_client.post(
            "/api/storage/nodes",
            headers=auth_headers,
            json={"parent_id": root_id, "name": "Freezer-1", "node_type": "space", "rows": 2, "cols": 3},
        ),
        201,
    )["item"]
    rack = api_ok(
        app_client.post(
            "/api/storage/nodes",
            headers=auth_headers,
            json={"parent_id": freezer["id"], "name": "Rack-A", "node_type": "space", "rows": 4, "cols": 4},
        ),
        201,
    )["item"]
    box = api_ok(
        app_client.post(
            "/api/storage/nodes",
            headers=auth_headers,
            json={"parent_id": rack["id"], "name": "Box-A", "node_type": "box", "rows": 9, "cols": 9},
        ),
        201,
    )["item"]

    forgiving_space = api_ok(
        app_client.post(
            "/api/storage/nodes",
            headers=auth_headers,
            json={"parent_id": freezer["id"], "name": "Forgiving-space", "node_type": "space", "sort_order": ""},
        ),
        201,
    )["item"]
    assert forgiving_space["sort_order"] == 0

    sample_result = api_ok(
        app_client.post(
            "/api/inventory/items",
            headers=auth_headers,
            json={
                "item_type": "sample",
                "name": "P-SMOKE-001",
                "category": "组织",
                "tube_count": 2,
                "separate_items": True,
                "amount": 0.5,
                "amount_unit": "mL",
                "status": "可用",
                "storage_node_id": box["id"],
                "position_in_box": "A1",
            },
        ),
        201,
    )
    assert sample_result["count"] == 2
    sample_items = sample_result["items"]
    assert [item["position_in_box"] for item in sample_items] == ["A1", "A2"]

    reagent = api_ok(
        app_client.post(
            "/api/inventory/items",
            headers=auth_headers,
            json={
                "item_type": "reagent",
                "name": "Ab-test",
                "category": "抗体",
                "brand": "CST",
                "catalog_no": "SMOKE-CAT",
                "quantity": 1,
                "status": "可用",
                "validation_status": "未验证",
                "storage_node_id": box["id"],
                "position_in_box": "B1",
            },
        ),
        201,
    )["item"]

    box_visual = api_ok(app_client.get(f"/api/storage/visual?node_id={box['id']}", headers=auth_headers))
    occupied = {well["coord"]: well["item"]["code"] for well in box_visual["wells"] if well["occupied"]}
    assert sample_items[0]["code"] in occupied["A1"]
    assert reagent["code"] in occupied["B1"]

    shrink_sample = api_ok(
        app_client.post(
            "/api/inventory/items",
            headers=auth_headers,
            json={
                "item_type": "sample",
                "name": "P-SHRINK-001",
                "category": "组织",
                "tube_count": 1,
                "status": "可用",
                "storage_node_id": box["id"],
                "position_in_box": "A9",
            },
        ),
        201,
    )["item"]
    shrink_result = api_ok(
        app_client.patch(
            f"/api/storage/nodes/{box['id']}",
            headers=auth_headers,
            json={"cols": 8},
        )
    )
    assert shrink_result["cleared_out_of_bounds"]["samples"] == 1
    shrink_detail = api_ok(
        app_client.get(f"/api/inventory/items/sample/{shrink_sample['id']}", headers=auth_headers)
    )["item"]
    assert shrink_detail["storage_node_id"] == box["id"]
    assert shrink_detail["position_in_box"] in ("", None)
    box_visual = api_ok(app_client.get(f"/api/storage/visual?node_id={box['id']}", headers=auth_headers))
    direct_ids_without_position = {
        item["id"] for item in box_visual["direct_items"]
        if item["item_type"] == "sample" and not item.get("position_in_box")
    }
    assert shrink_sample["id"] in direct_ids_without_position

    freezer_search = api_ok(
        app_client.get(f"/api/inventory/search?type=reagent&storage_node_id={freezer['id']}", headers=auth_headers)
    )
    assert any(item["id"] == reagent["id"] for item in freezer_search["items"])

    path_keyword_search = api_ok(
        app_client.get("/api/inventory/search?type=all&keyword=Freezer-1", headers=auth_headers)
    )
    assert any(item["item_type"] == "reagent" and item["id"] == reagent["id"] for item in path_keyword_search["items"])

    keyword_search = api_ok(
        app_client.get("/api/inventory/search?type=reagent&keyword=SMOKE-CAT&page=1&page_size=1", headers=auth_headers)
    )
    assert keyword_search["total"] >= 1
    assert keyword_search["page"] == 1
    assert keyword_search["page_size"] == 1
    assert keyword_search["items"][0]["id"] == reagent["id"]

    forgiving_search = api_ok(
        app_client.get("/api/inventory/search?type=reagent&page=bad&page_size=9999&storage_node_id=bad", headers=auth_headers)
    )
    assert forgiving_search["page"] == 1
    assert forgiving_search["page_size"] == 500

    api_ok(app_client.get("/api/inventory/catalog-conflicts?exclude_id=bad", headers=auth_headers))
    bad_timeline = app_client.get("/api/inventory/timeline?item_type=reagent&id=bad", headers=auth_headers)
    assert bad_timeline.status_code == 400
    api_ok(app_client.get("/api/storage/visual?node_id=bad&item_id=bad", headers=auth_headers))

    forgiving_expiration = api_ok(app_client.get("/api/expiration?days=bad", headers=auth_headers))
    assert forgiving_expiration["remind_days"] > 0
    excel_export = app_client.get("/api/excel/export?limit=bad&mode=template", headers=auth_headers)
    assert excel_export.status_code == 200

    sample_search = api_ok(
        app_client.get("/api/inventory/search?type=sample&keyword=P-SMOKE-001&available=1", headers=auth_headers)
    )
    assert sample_search["count"] >= 2

    unplaced_reagent = api_ok(
        app_client.post(
            "/api/inventory/items",
            headers=auth_headers,
            json={
                "item_type": "reagent",
                "name": "Unplaced reagent",
                "category": "抗体",
                "quantity": 1,
                "status": "可用",
            },
        ),
        201,
    )["item"]
    assert unplaced_reagent["storage_node_id"] is None
    assert unplaced_reagent["storage_location"] == "未归位"

    unplaced_sample = api_ok(
        app_client.post(
            "/api/inventory/items",
            headers=auth_headers,
            json={
                "item_type": "sample",
                "name": "P-UNPLACED-001",
                "category": "血清",
                "tube_count": 1,
                "status": "可用",
            },
        ),
        201,
    )["item"]
    assert unplaced_sample["storage_node_id"] is None
    assert unplaced_sample["storage_location"] == "未归位"

    unplaced_visual = api_ok(app_client.get("/api/storage/visual?node_id=-1", headers=auth_headers))
    assert unplaced_visual["current"]["id"] == -1
    assert unplaced_visual["current"]["name"] == "未归位"
    assert {item["item_type"] for item in unplaced_visual["direct_items"]} >= {"reagent", "sample"}

    moved = api_ok(
        app_client.post(
            "/api/movements",
            headers=auth_headers,
            json={"item_type": "sample", "item_id": sample_items[1]["id"], "to_storage_node_id": freezer["id"], "reason": "整理库存"},
        ),
        201,
    )["item"]
    assert moved["to_storage_node_id"] == freezer["id"]

    import db.database as database

    with database.connect() as conn:
        movement_count = conn.execute("SELECT COUNT(*) AS n FROM movements").fetchone()["n"]
    unchanged_move = api_ok(
        app_client.post(
            "/api/movements",
            headers=auth_headers,
            json={"item_type": "sample", "item_id": sample_items[1]["id"], "to_storage_node_id": freezer["id"], "reason": "拖拽移动"},
        ),
        201,
    )["item"]
    assert unchanged_move["unchanged"] is True
    assert unchanged_move["to_storage_node_id"] == freezer["id"]
    assert unchanged_move["can_rollback"] is False
    with database.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM movements").fetchone()["n"] == movement_count

    checkout = api_ok(
        app_client.post(
            "/api/checkouts",
            headers=auth_headers,
            json={"item_type": "sample", "item_id": sample_items[0]["id"], "reason": "实验消耗"},
        ),
        201,
    )["item"]
    assert checkout["to_location"] == "已出库"

    limited_user = api_ok(
        app_client.post(
            "/api/users",
            headers=auth_headers,
            json={
                "username": "limited",
                "password": "secret123",
                "display_name": "Limited User",
                "role": "user",
                "permissions": {"inventory.manage": False, "location.manage": False, "inventory.search": False},
            },
        ),
        201,
    )["item"]
    assert limited_user["permissions"]["inventory.search"] is False

    limited_login = api_ok(app_client.post("/api/login", json={"username": "limited", "password": "secret123"}))
    limited_headers = {"Authorization": f"Bearer {limited_login['token']}"}

    denied_search = app_client.get("/api/inventory/search?type=all&keyword=Ab-test&purpose=global", headers=limited_headers)
    assert denied_search.status_code == 403
    denied_move = app_client.post(
        "/api/movements",
        headers=limited_headers,
        json={"item_type": "reagent", "item_id": reagent["id"], "to_storage_node_id": freezer["id"]},
    )
    assert denied_move.status_code == 403

    occupied_delete = app_client.delete(f"/api/storage/nodes/{box['id']}", headers=auth_headers)
    assert occupied_delete.status_code == 400

    limited_order = api_ok(
        app_client.post(
            "/api/orders",
            headers=limited_headers,
            json={"name": "Limited-order", "category": "其他", "quantity": 1},
        ),
        201,
    )["item"]
    assert limited_order["name"] == "Limited-order"

    arrival = api_ok(
        app_client.post(
            "/api/arrivals",
            headers=auth_headers,
            json={"order_id": limited_order["id"], "arrival_quantity": 1},
        ),
        201,
    )
    assert arrival["items"][0]["storage_node_id"] is None
    assert arrival["items"][0]["storage_location"] == "未归位"

    empty_bin = api_ok(
        app_client.post(
            "/api/storage/nodes",
            headers=auth_headers,
            json={"parent_id": freezer["id"], "name": "Empty-bin", "node_type": "space"},
        ),
        201,
    )["item"]

    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO arrivals
                (order_id, item_type, item_id, entry_date, received_by, storage_node_id, position_in_box, location_snapshot, expiration_date, note, created_at)
            VALUES (NULL, 'reagent', ?, '2026-06-01', 1, ?, 'A1', 'Empty-bin / A1', '', '', '2026-06-01 09:00:00')
            """,
            (reagent["id"], empty_bin["id"]),
        )
        conn.execute(
            """
            INSERT INTO movements
                (object_type, object_id, item_type, item_id, from_storage_node_id, from_position_in_box,
                 to_storage_node_id, to_position_in_box, from_location_snapshot, to_location_snapshot, moved_by, moved_at, reason, note)
            VALUES ('试剂', ?, 'reagent', ?, ?, 'A1', ?, 'B1', 'Empty-bin / A1', 'Empty-bin / B1', 1, '2026-06-01 10:00:00', '历史引用测试', '')
            """,
            (reagent["code"], reagent["id"], empty_bin["id"], empty_bin["id"]),
        )
        conn.commit()

    deleted = api_ok(app_client.delete(f"/api/storage/nodes/{empty_bin['id']}", headers=auth_headers))
    assert deleted["cleared_history_refs"] == {"arrivals": 1, "movement_refs": 2}
    with database.connect() as conn:
        arrival = conn.execute("SELECT storage_node_id, position_in_box, location_snapshot FROM arrivals ORDER BY id DESC LIMIT 1").fetchone()
        movement = conn.execute("SELECT from_storage_node_id, to_storage_node_id FROM movements ORDER BY id DESC LIMIT 1").fetchone()
        assert arrival["storage_node_id"] is None
        assert arrival["position_in_box"] is None
        assert arrival["location_snapshot"] == "Empty-bin / A1"
        assert movement["from_storage_node_id"] is None
        assert movement["to_storage_node_id"] is None


def test_emergency_excel_export_skips_internal_tables(app_client, auth_headers):
    from io import BytesIO

    from openpyxl import load_workbook

    table_data = api_ok(app_client.get("/api/excel/tables", headers=auth_headers))
    table_names = {item["name"] for item in table_data["items"]}
    assert "reagents" in table_names
    assert "schema_migrations" not in table_names

    response = app_client.get("/api/excel/export?mode=data&limit=5", headers=auth_headers)
    assert response.status_code == 200, response.text
    workbook = load_workbook(BytesIO(response.content), read_only=True)
    assert "reagents" in workbook.sheetnames
    assert "schema_migrations" not in workbook.sheetnames


def test_health_hides_database_path_in_production(app_client, monkeypatch):
    import routers.core as core_routes

    monkeypatch.setattr(core_routes, "IS_PRODUCTION", True)
    production_health = api_ok(app_client.get("/api/health"))
    assert production_health["ok"] is True
    assert "db" not in production_health

    monkeypatch.setattr(core_routes, "IS_PRODUCTION", False)
    development_health = api_ok(app_client.get("/api/health"))
    assert "db" in development_health
