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

    freezer_search = api_ok(
        app_client.get(f"/api/inventory/search?type=reagent&storage_node_id={freezer['id']}", headers=auth_headers)
    )
    assert any(item["id"] == reagent["id"] for item in freezer_search["items"])

    path_keyword_search = api_ok(
        app_client.get("/api/inventory/search?type=all&keyword=Freezer-1", headers=auth_headers)
    )
    assert any(item["item_type"] == "reagent" and item["id"] == reagent["id"] for item in path_keyword_search["items"])

    fts_search = api_ok(
        app_client.get("/api/inventory/search?type=reagent&keyword=SMOKE-CAT&page=1&page_size=1", headers=auth_headers)
    )
    assert fts_search["total"] >= 1
    assert fts_search["page"] == 1
    assert fts_search["page_size"] == 1
    assert fts_search["items"][0]["id"] == reagent["id"]

    sample_search = api_ok(
        app_client.get("/api/inventory/search?type=sample&keyword=P-SMOKE-001&available=1", headers=auth_headers)
    )
    assert sample_search["count"] >= 2

    moved = api_ok(
        app_client.post(
            "/api/movements",
            headers=auth_headers,
            json={"item_type": "sample", "item_id": sample_items[1]["id"], "to_storage_node_id": freezer["id"], "reason": "整理库存"},
        ),
        201,
    )["item"]
    assert moved["to_storage_node_id"] == freezer["id"]

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

    limited_order = api_ok(
        app_client.post(
            "/api/orders",
            headers=limited_headers,
            json={"name": "Limited-order", "category": "其他", "quantity": 1},
        ),
        201,
    )["item"]
    assert limited_order["name"] == "Limited-order"


def test_health_hides_database_path_in_production(app_client, monkeypatch):
    import routers.core as core_routes

    monkeypatch.setattr(core_routes, "IS_PRODUCTION", True)
    production_health = api_ok(app_client.get("/api/health"))
    assert production_health["ok"] is True
    assert "db" not in production_health

    monkeypatch.setattr(core_routes, "IS_PRODUCTION", False)
    development_health = api_ok(app_client.get("/api/health"))
    assert "db" in development_health
