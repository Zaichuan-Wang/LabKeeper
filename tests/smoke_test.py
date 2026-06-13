from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "db" / "lab_inventory.sqlite3"
OPTIONS_TEST_PATH = ROOT / "db" / "smoke_dropdown_options.json"
PORT = 8127
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def remove_sqlite_files(path: Path) -> None:
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists():
            candidate.unlink()


def request(path: str, method: str = "GET", token: str | None = None, payload: dict | None = None) -> dict:
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {body}") from exc


def request_error(path: str, method: str = "GET", token: str | None = None, payload: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def wait_until_ready() -> None:
    deadline = time.time() + 15
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            result = request("/api/health")
            if result.get("ok") is True:
                return
        except Exception as exc:  # noqa: BLE001 - smoke test keeps the last startup error.
            last_error = exc
        time.sleep(0.3)
    raise RuntimeError(f"API did not become ready: {last_error}")


def main() -> None:
    remove_sqlite_files(DB_PATH)
    if OPTIONS_TEST_PATH.exists():
        OPTIONS_TEST_PATH.unlink()

    env = os.environ.copy()
    env["LABKEEPER_ENV"] = "test"
    env["LABKEEPER_ENABLE_DEV_TOOLS"] = "1"
    env["LABKEEPER_OPTIONS_CONFIG"] = str(OPTIONS_TEST_PATH)
    stdout_log_path = ROOT / "smoke_backend.out.log"
    stderr_log_path = ROOT / "smoke_backend.err.log"
    stdout_log = stdout_log_path.open("w", encoding="utf-8")
    stderr_log = stderr_log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "backend" / "server.py"), "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT), env=env, stdout=stdout_log, stderr=stderr_log, text=True, encoding="utf-8",
    )
    try:
        wait_until_ready()
        login = request("/api/login", method="POST", payload={"username": "admin", "password": "admin123"})
        token = login["token"]
        assert login["user"]["username"] == "admin"

        dashboard = request("/api/dashboard", token=token)
        assert dashboard["metrics"]["total_reagents"] == 0

        tree = request("/api/storage/tree", token=token)
        normal_roots = [item for item in tree["items"] if item.get("parent_id") is None]
        assert all(not item.get("is_system") for item in tree["items"])
        assert len(normal_roots) == 1
        root_id = normal_roots[0]["id"]
        unplaced_visual = request("/api/storage/visual?node_id=-1", token=token)
        assert unplaced_visual["current"]["is_virtual_unplaced"] is True
        assert unplaced_visual["current"]["name"] == "未归位"
        assert unplaced_visual["children"] == []
        root_visual = request(f"/api/storage/visual?node_id={root_id}", token=token)
        assert root_visual["grid"]["rows"] == 1
        assert root_visual["grid"]["cols"] == 1
        assert root_visual["grid"]["is_framed"] is False
        freezer = request("/api/storage/nodes", method="POST", token=token, payload={"parent_id": root_id, "name": "Freezer-1", "node_type": "space", "rows": 2, "cols": 3})["item"]
        rack = request("/api/storage/nodes", method="POST", token=token, payload={"parent_id": freezer["id"], "name": "Rack-A", "node_type": "space", "rows": 4, "cols": 4, "grid_row": 2, "grid_col": 3})["item"]
        drawer = request("/api/storage/nodes", method="POST", token=token, payload={"parent_id": freezer["id"], "name": "Drawer-A", "node_type": "space", "rows": 1, "cols": 3, "grid_row": 1, "grid_col": 1})["item"]
        box = request("/api/storage/nodes", method="POST", token=token, payload={"parent_id": rack["id"], "name": "Box-A", "node_type": "box", "rows": 9, "cols": 9, "grid_row": 1, "grid_col": 1})["item"]
        box_child_status, box_child_body = request_error("/api/storage/nodes", method="POST", token=token, payload={"parent_id": box["id"], "name": "Invalid-child", "node_type": "space"})
        delete_freezer_status, delete_freezer_body = request_error(f"/api/storage/nodes/{freezer['id']}", method="DELETE", token=token)
        empty_space = request("/api/storage/nodes", method="POST", token=token, payload={"parent_id": root_id, "name": "Empty-Space", "node_type": "space"})["item"]
        deleted_space = request(f"/api/storage/nodes/{empty_space['id']}", method="DELETE", token=token)
        deleted_tree = request("/api/storage/tree", token=token)
        freezer_visual = request(f"/api/storage/visual?node_id={freezer['id']}", token=token)
        assert freezer_visual["grid"]["rows"] == 2
        assert freezer_visual["grid"]["is_framed"] is True
        assert {child["node_type"] for child in freezer_visual["children"]} == {"space"}
        assert next(child for child in freezer_visual["children"] if child["id"] == rack["id"])["grid_label"] == "B3"
        assert drawer["node_type"] == "space"
        assert box_child_status == 400
        assert "盒子已是末端空间" in box_child_body
        assert delete_freezer_status == 400
        assert "下级空间" in delete_freezer_body
        assert deleted_space["deleted_id"] == empty_space["id"]
        assert all(item["id"] != empty_space["id"] for item in deleted_tree["items"])
        drawer_unplaced = request(
            f"/api/storage/nodes/{drawer['id']}",
            method="PATCH",
            token=token,
            payload={"parent_id": freezer["id"], "grid_row": "", "grid_col": ""},
        )["item"]
        freezer_visual_unplaced = request(f"/api/storage/visual?node_id={freezer['id']}", token=token)
        drawer_visual = next(child for child in freezer_visual_unplaced["children"] if child["id"] == drawer["id"])
        assert drawer_unplaced["grid_row"] is None
        assert drawer_unplaced["grid_col"] is None
        assert drawer_visual["is_unplaced"] is True
        drawer_global_unplaced = request(
            f"/api/storage/nodes/{drawer['id']}",
            method="PATCH",
            token=token,
            payload={"parent_id": "", "grid_row": "", "grid_col": ""},
        )["item"]
        unplaced_with_space = request("/api/storage/visual?node_id=-1", token=token)
        assert drawer_global_unplaced["parent_id"] is None
        assert any(child["id"] == drawer["id"] for child in unplaced_with_space["children"])
        drawer_back_to_root = request(
            f"/api/storage/nodes/{drawer['id']}",
            method="PATCH",
            token=token,
            payload={"parent_id": root_id, "grid_row": "", "grid_col": ""},
        )["item"]
        root_visual_with_drawer = request(f"/api/storage/visual?node_id={root_id}", token=token)
        assert drawer_back_to_root["parent_id"] == root_id
        assert any(child["id"] == drawer["id"] for child in root_visual_with_drawer["children"])

        sample_result = request(
            "/api/inventory/items",
            method="POST",
            token=token,
            payload={
                "item_type": "sample",
                "tube_count": 2,
                "name": "P-SMOKE-001",
                "category": "组织",
                "amount": 25,
                "amount_unit": "mg",
                "storage_node_id": box["id"],
                "position_in_box": "A1",
                "entry_date": "2026-06-09",
            },
        )
        sample = sample_result["item"]
        sample_items = sample_result["items"]
        sample_detail = request(f"/api/inventory/items/sample/{sample['id']}", token=token)
        visual_sample = request(f"/api/storage/visual?node_id={box['id']}&well=A1", token=token)
        delete_box_status, delete_box_body = request_error(f"/api/storage/nodes/{box['id']}", method="DELETE", token=token)
        assert sample_result["count"] == 2
        assert sample_items[0]["code"].startswith("SMP")
        assert sample_items[1]["code"].startswith("SMP")
        assert sample_items[0]["code"] != sample_items[1]["code"]
        assert [item["name"] for item in sample_items] == ["P-SMOKE-001", "P-SMOKE-001"]
        assert [item["category"] for item in sample_items] == ["组织", "组织"]
        assert [item["aliquot_no"] for item in sample_items] == [1, 2]
        assert sample["aliquot_no"] == 1
        assert sample["amount"] == 25
        assert sample["amount_unit"] == "mg"
        assert "A1" in sample["storage_location"]
        assert sample["quantity"] == 1
        assert sample_detail["item"]["code"] == sample["code"]
        assert visual_sample["selected_item"]["item_type"] == "sample"
        assert delete_box_status == 400
        assert "库存" in delete_box_body
        assert visual_sample["selected_item"]["code"] == sample["code"]
        sample_search = request("/api/inventory/search?type=sample&keyword=P-SMOKE-001&available=1", token=token)
        assert any(item["id"] == sample["id"] for item in sample_search["items"])
        unplaced_sample = request(
            "/api/inventory/items",
            method="POST",
            token=token,
            payload={
                "item_type": "sample",
                "name": "P-SMOKE-001",
                "category": "血清",
                "amount": 1,
                "amount_unit": "mL",
                "entry_date": "2026-06-09",
            },
        )["item"]
        assert unplaced_sample["name"] == sample["name"]
        assert unplaced_sample["category"] == "血清"
        assert unplaced_sample["code"] != sample["code"]
        assert unplaced_sample["storage_node_id"] is None
        assert unplaced_sample["storage_location"] == "未归位"
        combined_sample = request(
            "/api/inventory/items",
            method="POST",
            token=token,
            payload={
                "item_type": "sample",
                "tube_count": 3,
                "separate_items": False,
                "name": "P-SMOKE-COMBINED",
                "category": "血浆",
                "amount": 0.5,
                "amount_unit": "mL",
                "entry_date": "2026-06-09",
            },
        )
        assert combined_sample["count"] == 1
        assert combined_sample["item"]["quantity"] == 3
        assert combined_sample["item"]["aliquot_no"] is None

        order = request("/api/orders", method="POST", token=token, payload={"name": "Ab-test", "category": "antibody", "catalog_no": "SMOKE-CAT", "quantity": 1})["item"]
        conflict_status, conflict_body = request_error(
            "/api/arrivals",
            method="POST",
            token=token,
            payload={"order_id": order["id"], "storage_node_id": box["id"], "position_in_box": "A1", "entry_date": "2026-06-08"},
        )
        assert conflict_status == 409
        assert "A1" in conflict_body
        arrival = request("/api/arrivals", method="POST", token=token, payload={"order_id": order["id"], "storage_node_id": box["id"], "position_in_box": "B2", "entry_date": "2026-06-08"})
        reagent_id = arrival["item_id"]
        unplaced_order = request("/api/orders", method="POST", token=token, payload={"name": "No-location", "category": "其他", "quantity": 1})["item"]
        unplaced_arrival = request("/api/arrivals", method="POST", token=token, payload={"order_id": unplaced_order["id"], "entry_date": "2026-06-08"})
        assert unplaced_arrival["item"]["storage_node_id"] is None
        assert unplaced_arrival["item"]["storage_location"] == "未归位"
        combined_order = request("/api/orders", method="POST", token=token, payload={"name": "Combined-arrival", "category": "其他", "quantity": 3})["item"]
        combined_arrival = request("/api/arrivals", method="POST", token=token, payload={"order_id": combined_order["id"], "arrival_quantity": 3, "separate_items": False, "entry_date": "2026-06-08"})
        combined_reagent = request(f"/api/inventory/items/reagent/{combined_arrival['item_id']}", token=token)["item"]
        assert combined_arrival["count"] == 1
        assert combined_reagent["quantity"] == 3
        split_reagent = request(
            "/api/inventory/items",
            method="POST",
            token=token,
            payload={"item_type": "reagent", "name": "Split reagent", "category": "其他", "quantity": 2},
        )
        assert split_reagent["count"] == 2
        assert [item["quantity"] for item in split_reagent["items"]] == [1, 1]
        combined_manual_reagent = request(
            "/api/inventory/items",
            method="POST",
            token=token,
            payload={"item_type": "reagent", "name": "Combined reagent", "category": "其他", "quantity": 4, "separate_items": False},
        )
        assert combined_manual_reagent["count"] == 1
        assert combined_manual_reagent["item"]["quantity"] == 4
        unplaced_after_arrival = request("/api/storage/visual?node_id=-1", token=token)
        unplaced_codes = {item["code"] for item in unplaced_after_arrival["items"]}
        assert unplaced_sample["code"] in unplaced_codes
        assert any(item["item_type"] == "reagent" and item["storage_node_id"] is None for item in unplaced_after_arrival["items"])

        visual = request(f"/api/storage/visual?node_id={box['id']}", token=token)
        assert len(visual["wells"]) == 81
        assert visual["stats"]["occupied"] == 3
        sample_movement = request(
            "/api/movements",
            method="POST",
            token=token,
            payload={"item_type": "sample", "item_id": sample_items[1]["id"], "to_storage_node_id": drawer["id"], "reason": "sample move smoke"},
        )["item"]
        moved_sample_detail = request(f"/api/inventory/items/sample/{sample_items[1]['id']}", token=token)
        sample_unplaced_movement = request(
            "/api/movements",
            method="POST",
            token=token,
            payload={"item_type": "sample", "item_id": sample_items[1]["id"], "to_storage_node_id": "", "reason": "sample unplaced smoke"},
        )["item"]
        unplaced_sample_detail = request(f"/api/inventory/items/sample/{sample_items[1]['id']}", token=token)

        validation = request("/api/validations", method="POST", token=token, payload={"catalog_no": "SMOKE-CAT", "result": "通过", "method": "WB"})["item"]
        movement = request("/api/movements", method="POST", token=token, payload={"item_type": "reagent", "item_id": reagent_id, "to_storage_node_id": freezer["id"], "reason": "smoke"})["item"]
        updated_reagent = request(
            f"/api/inventory/items/reagent/{reagent_id}",
            method="PATCH",
            token=token,
            payload={"quantity": 2, "storage_node_id": box["id"], "position_in_box": "B2"},
        )["item"]
        detail = request(f"/api/inventory/items/reagent/{reagent_id}", token=token)
        visual_selected = request(f"/api/storage/visual?node_id={box['id']}&well=B2", token=token)
        consumed_reagent = request(
            f"/api/inventory/items/reagent/{reagent_id}",
            method="PATCH",
            token=token,
            payload={"status": "已耗尽", "quantity": 0, "storage_node_id": box["id"], "position_in_box": "B2"},
        )["item"]
        detail_after_consumed = request(f"/api/inventory/items/reagent/{reagent_id}", token=token)
        visual_after_consumed = request(f"/api/storage/visual?node_id={box['id']}&well=B2", token=token)
        movements_after_consumed = request("/api/movements", token=token)
        checkout = request("/api/checkouts", method="POST", token=token, payload={"item_type": "sample", "item_id": sample["id"], "reason": "smoke checkout"})["item"]
        checkouts_history = request("/api/checkouts", token=token)
        movements_after_checkout = request("/api/movements", token=token)
        expiration = request("/api/expiration?days=60", token=token)
        catalog_conflict = request("/api/inventory/catalog-conflicts?catalog_no=SMOKE-CAT&name=Different-name", token=token)
        dropdowns = request("/api/settings/dropdowns", token=token)
        saved_dropdowns = request(
            "/api/settings/dropdowns",
            method="PATCH",
            token=token,
            payload={**dropdowns["item"], "categories": dropdowns["item"]["categories"] + ["烟雾测试"]},
        )
        patched_box = request(f"/api/storage/nodes/{box['id']}", method="PATCH", token=token, payload={"name": "Box-B", "rows": 8, "cols": 12})["item"]
        created_user = request(
            "/api/users",
            method="POST",
            token=token,
            payload={
                "username": "smoke",
                "password": "secret123",
                "role": "user",
                "permissions": {"inventory.manage": True, "location.manage": False, "inventory.search": True},
            },
        )["item"]
        patched_user = request(f"/api/users/{created_user['id']}", method="PATCH", token=token, payload={"display_name": "Smoke User", "is_active": False})["item"]
        limited_user = request(
            "/api/users",
            method="POST",
            token=token,
            payload={
                "username": "limited",
                "password": "secret123",
                "role": "user",
                "permissions": {"inventory.manage": False, "location.manage": False, "inventory.search": False},
            },
        )["item"]
        limited_login = request("/api/login", method="POST", payload={"username": "limited", "password": "secret123"})
        limited_token = limited_login["token"]
        limited_search_status, _limited_search_body = request_error("/api/inventory/search?type=all&keyword=Ab-test&purpose=global", token=limited_token)
        limited_move_status, _limited_move_body = request_error("/api/movements", method="POST", token=limited_token, payload={"item_type": "reagent", "item_id": reagent_id, "to_storage_node_id": freezer["id"]})
        limited_order = request("/api/orders", method="POST", token=limited_token, payload={"name": "Limited-order", "category": "其他", "quantity": 1})["item"]
        excel_tables = request("/api/excel/tables", token=token)
        users = request("/api/users", token=token)
        reagents = request("/api/inventory/search?type=reagent", token=token)
        reagent_search = request("/api/inventory/search?type=reagent&keyword=Ab-test", token=token)

        assert validation["id"] >= 1
        assert validation["catalog_no"] == "SMOKE-CAT"
        assert movement["id"] >= 1
        assert sample_movement["object_type"] == "临床标本"
        assert sample_movement["to_location"].endswith("Drawer-A")
        assert moved_sample_detail["item"]["storage_node_id"] == drawer["id"]
        assert moved_sample_detail["item"]["position_in_box"] in ("", None)
        assert sample_unplaced_movement["to_storage_node_id"] is None
        assert sample_unplaced_movement["to_location"] == "未归位"
        assert unplaced_sample_detail["item"]["storage_node_id"] is None
        assert unplaced_sample_detail["item"]["storage_location"] == "未归位"
        assert updated_reagent["quantity"] == 2
        assert detail["item"]["id"] == reagent_id
        assert visual_selected["selected_item"]["id"] == reagent_id
        assert consumed_reagent["status"] == "已耗尽"
        assert consumed_reagent["quantity"] == 0
        assert consumed_reagent["storage_node_id"] is None
        assert consumed_reagent["storage_location"] in ("", None)
        assert consumed_reagent["position_in_box"] in ("", None)
        assert detail_after_consumed["item"]["id"] == reagent_id
        assert detail_after_consumed["validations"][0]["result"] == "通过"
        assert detail_after_consumed["validations"][0]["catalog_no"] == "SMOKE-CAT"
        assert visual_after_consumed["selected_item"] is None
        assert visual_after_consumed["stats"]["occupied"] == 1
        assert any(row["item_type"] == "reagent" and row["item_id"] == reagent_id and row["to_location"] == "未放置（已耗尽）" for row in movements_after_consumed["items"])
        assert checkout["to_location"] == "已出库"
        assert any(row["id"] == checkout["id"] for row in checkouts_history["items"])
        assert all(row["id"] != checkout["id"] for row in movements_after_checkout["items"])
        assert expiration["remind_days"] == 60
        assert "pending_orders" in expiration
        assert "unvalidated_antibodies" in expiration
        assert catalog_conflict["has_conflict"] is True
        assert "烟雾测试" in saved_dropdowns["item"]["categories"]
        assert patched_box["rows"] == 8
        assert patched_user["is_active"] == 0
        assert created_user["role"] == "user"
        assert created_user["permissions"]["inventory.manage"] is True
        assert created_user["permissions"]["location.manage"] is False
        assert limited_search_status == 403
        assert limited_move_status == 403
        assert limited_order["name"] == "Limited-order"
        assert any(item["name"] == "reagents" for item in excel_tables["items"])
        assert any(item["name"] == "inventory_checklist" and item.get("virtual") for item in excel_tables["items"])
        assert users["count"] == 3
        assert reagents["count"] == 2
        assert reagent_search["items"][0]["id"] == reagent_id
        print(json.dumps({"status": "ok", "fresh_db": str(DB_PATH), "reagent_id": reagent_id, "box_wells": len(visual["wells"])}, ensure_ascii=False))
    finally:
        stdout_log.close()
        stderr_log.close()
        if proc.poll() not in (None, 0):
            stdout = stdout_log_path.read_text(encoding="utf-8", errors="replace") if stdout_log_path.exists() else ""
            stderr = stderr_log_path.read_text(encoding="utf-8", errors="replace") if stderr_log_path.exists() else ""
            print("backend stdout:", stdout[-4000:])
            print("backend stderr:", stderr[-4000:])
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        remove_sqlite_files(DB_PATH)
        if OPTIONS_TEST_PATH.exists():
            OPTIONS_TEST_PATH.unlink()


if __name__ == "__main__":
    main()
