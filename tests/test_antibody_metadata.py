def api_ok(response, status_code=200):
    assert response.status_code == status_code, response.text
    return response.json()


def test_antibody_metadata_create_get_and_patch(app_client, auth_headers):
    created = api_ok(
        app_client.post(
            "/api/antibody-metadata",
            headers=auth_headers,
            json={
                "catalog_no": "300412",
                "target": "CD3",
                "conjugate": "APC",
                "react_species": "Human",
                "host_species": "Mouse",
                "clone": "SK7",
                "isotype": "IgG1 κ",
                "aliases": "UCHT1",
                "raw_note": "原始表备注",
            },
        ),
        201,
    )["item"]
    assert created["catalog_no"] == "300412"
    assert created["target"] == "CD3"
    assert created["host_species"] == "Mouse"

    fetched = api_ok(
        app_client.get("/api/antibody-metadata?catalog_no=300412", headers=auth_headers)
    )["item"]
    assert fetched["clone"] == "SK7"
    assert fetched["isotype"] == "IgG1 κ"

    duplicate = app_client.post(
        "/api/antibody-metadata",
        headers=auth_headers,
        json={"catalog_no": "300412", "target": "CD3"},
    )
    assert duplicate.status_code == 409

    updated = api_ok(
        app_client.patch(
            "/api/antibody-metadata?catalog_no=300412",
            headers=auth_headers,
            json={"conjugate": "APC-H7", "raw_note": ""},
        )
    )["item"]
    assert updated["target"] == "CD3"
    assert updated["conjugate"] == "APC-H7"
    assert updated["raw_note"] == ""


def test_antibody_metadata_requires_catalog_no(app_client, auth_headers):
    missing_create = app_client.post(
        "/api/antibody-metadata",
        headers=auth_headers,
        json={"target": "CD45"},
    )
    assert missing_create.status_code == 400

    missing_get = app_client.get("/api/antibody-metadata", headers=auth_headers)
    assert missing_get.status_code == 400

    missing_patch = app_client.patch(
        "/api/antibody-metadata",
        headers=auth_headers,
        json={"target": "CD45"},
    )
    assert missing_patch.status_code == 400


def test_antibody_metadata_unknown_catalog_returns_null(app_client, auth_headers):
    fetched = api_ok(
        app_client.get("/api/antibody-metadata?catalog_no=UNKNOWN-CAT", headers=auth_headers)
    )
    assert fetched["item"] is None


def test_reagent_detail_includes_antibody_metadata(app_client, auth_headers):
    reagent = api_ok(
        app_client.post(
            "/api/inventory/items",
            headers=auth_headers,
            json={
                "item_type": "reagent",
                "name": "Anti-CD8 FITC",
                "category": "抗体",
                "catalog_no": "AB-DETAIL-1",
                "quantity": 1,
                "antibody_target": "CD8",
                "antibody_conjugate": "FITC",
            },
        ),
        201,
    )["item"]
    api_ok(
        app_client.post(
            "/api/antibody-metadata",
            headers=auth_headers,
            json={
                "catalog_no": "AB-DETAIL-1",
                "target": "CD8",
                "conjugate": "FITC",
                "react_species": "Human",
                "host_species": "Mouse",
                "clone": "RPA-T8",
                "isotype": "IgG1 κ",
            },
        ),
        201,
    )

    detail = api_ok(
        app_client.get(
            f"/api/inventory/item?item_type=reagent&id={reagent['id']}",
            headers=auth_headers,
        )
    )

    assert detail["antibody_metadata"]["catalog_no"] == "AB-DETAIL-1"
    assert detail["antibody_metadata"]["target"] == "CD8"
    assert detail["antibody_metadata"]["clone"] == "RPA-T8"


def test_reagent_ai_extract_passes_brand_options_to_qwen_and_returns_item(app_client, auth_headers, monkeypatch):
    from services import ai_antibody

    captured = {}

    def fake_request(prompt):
        captured["prompt"] = prompt
        return """
        {
          "name": "Anti-CD45 APC",
          "category": "抗体",
          "brand": "Thermo Fisher Scientific",
          "catalog_no": "17-0459-42",
          "amount": 100,
          "amount_unit": "uL",
          "quantity": 2,
          "price": null,
          "reason": "流式抗体补货",
          "note": "需核对产品页",
          "is_antibody": true,
          "antibody": {
            "target": "CD45",
            "conjugate": "APC",
            "react_species": "Human",
            "host_species": "Mouse",
            "clone": "HI30",
            "isotype": "IgG1",
            "aliases": "",
            "raw_note": "AI 提取，需人工核对"
          },
          "confidence": 0.76,
          "warnings": ["品牌需按本地品牌列表核对"]
        }
        """

    monkeypatch.setattr(ai_antibody.config, "QWEN_API_KEY", "test-key")
    monkeypatch.setattr(ai_antibody, "_request_qwen", fake_request)
    result = api_ok(
        app_client.post(
            "/api/reagents/ai-extract",
            headers=auth_headers,
            json={
                "text": "https://example.test/product/17-0459-42 Thermo Fisher anti-CD45 APC",
                "form_context": "order",
                "categories": ["抗体", "试剂盒", "其他"],
                "brands": ["Thermo Fisher", "BioLegend"],
                "amount_units": ["uL", "mL"],
                "antibody_conjugates": ["APC"],
                "antibody_react_species": ["Human"],
                "antibody_host_species": ["Mouse"],
                "antibody_isotypes": ["IgG1"],
            },
        )
    )
    prompt_text = captured["prompt"]
    assert "Thermo Fisher" in prompt_text
    assert "BioLegend" in prompt_text
    assert "优先归一化到 brands 中已有写法" in prompt_text
    assert result["item"]["category"] == "抗体"
    assert result["item"]["brand"] == "Thermo Fisher Scientific"
    assert result["item"]["catalog_no"] == "17-0459-42"
    assert result["antibody"]["target"] == "CD45"
    assert result["confidence"] == 0.76


def test_reagent_ai_extract_builds_catalog_search_queries(app_client, auth_headers, monkeypatch):
    from services import ai_antibody

    captured = {}

    def fake_request(prompt):
        captured["prompt"] = prompt
        return """
        {
          "name": "Anti-NK-1R antibody",
          "category": "抗体",
          "brand": "Abcam",
          "catalog_no": "ab61705",
          "amount": null,
          "amount_unit": "",
          "quantity": null,
          "price": null,
          "reason": "",
          "note": "",
          "is_antibody": true,
          "antibody": {
            "target": "NK-1R",
            "conjugate": "",
            "react_species": "",
            "host_species": "Goat",
            "clone": "",
            "isotype": "",
            "aliases": "",
            "raw_note": "AI 提取，需人工核对"
          },
          "confidence": 0.7,
          "warnings": []
        }
        """

    monkeypatch.setattr(ai_antibody.config, "QWEN_API_KEY", "test-key")
    monkeypatch.setattr(ai_antibody, "_request_qwen", fake_request)
    result = api_ok(
        app_client.post(
            "/api/reagents/ai-extract",
            headers=auth_headers,
            json={
                "text": "NK-1R goatab61705 abcam",
                "form_context": "reagent",
                "categories": ["抗体", "试剂盒", "其他"],
                "brands": ["Abcam", "BioLegend"],
                "amount_units": ["uL", "mL"],
            },
        )
    )
    prompt_text = captured["prompt"]
    assert "search_queries" in prompt_text
    assert "必须先使用 web_search" in prompt_text
    assert "NK-1R" in prompt_text
    assert "Abcam" in prompt_text
    assert "ab61705" in prompt_text
    assert result["item"]["catalog_no"] == "ab61705"


def test_reagent_ai_extract_normalizes_unlabeled_antibody_conjugate(app_client, auth_headers, monkeypatch):
    from services import ai_antibody

    captured = {}

    def fake_request(prompt):
        captured["prompt"] = prompt
        return """
        {
          "name": "Anti-beta Actin purified antibody",
          "category": "抗体",
          "brand": "CST",
          "catalog_no": "4970",
          "amount": 100,
          "amount_unit": "uL",
          "quantity": 1,
          "price": null,
          "reason": "",
          "note": "",
          "is_antibody": true,
          "antibody": {
            "target": "beta Actin",
            "conjugate": "Purified",
            "react_species": "Human/Mouse/Rat",
            "host_species": "Rabbit",
            "clone": "13E5",
            "isotype": "",
            "aliases": "",
            "raw_note": "用于间接法的一抗"
          },
          "confidence": 0.8,
          "warnings": []
        }
        """

    monkeypatch.setattr(ai_antibody.config, "QWEN_API_KEY", "test-key")
    monkeypatch.setattr(ai_antibody, "_request_qwen", fake_request)
    result = api_ok(
        app_client.post(
            "/api/reagents/ai-extract",
            headers=auth_headers,
            json={
                "text": "CST 4970 purified beta Actin antibody",
                "form_context": "reagent",
                "categories": ["抗体", "其他"],
                "brands": ["CST"],
                "amount_units": ["uL"],
                "antibody_conjugates": ["HRP", "AF488", "Unlabeled"],
            },
        )
    )

    assert "未偶联" in captured["prompt"]
    assert "不要把间接法写成 Indirect" in captured["prompt"]
    assert result["antibody"]["conjugate"] == "Unlabeled"


def test_antibody_metadata_can_be_written_by_reagent_visible_order_user(app_client, auth_headers):
    api_ok(
        app_client.post(
            "/api/users",
            headers=auth_headers,
            json={
                "username": "buyer",
                "password": "buyer123",
                "display_name": "Buyer",
                "role": "user",
                "permissions": {
                    "inventory.manage": False,
                    "inventory.search": False,
                    "inventory.view_reagents": True,
                    "inventory.view_samples": False,
                },
            },
        ),
        201,
    )
    login = api_ok(app_client.post("/api/login", json={"username": "buyer", "password": "buyer123"}))
    buyer_headers = {"Authorization": f"Bearer {login['token']}"}

    order = api_ok(
        app_client.post(
            "/api/orders",
            headers=buyer_headers,
            json={
                "name": "抗CD25-PE",
                "category": "抗体",
                "catalog_no": "102005",
                "quantity": 1,
                "antibody_target": "CD25",
                "antibody_conjugate": "PE",
            },
        ),
        201,
    )["item"]
    assert order["catalog_no"] == "102005"

    created = api_ok(
        app_client.post(
            "/api/antibody-metadata",
            headers=buyer_headers,
            json={
                "catalog_no": "102005",
                "target": "CD25",
                "conjugate": "PE",
                "react_species": "Mouse",
                "host_species": "Rat",
                "isotype": "IgG1 κ",
            },
        ),
        201,
    )["item"]
    assert created["target"] == "CD25"
    assert created["host_species"] == "Rat"

    updated = api_ok(
        app_client.patch(
            "/api/antibody-metadata?catalog_no=102005",
            headers=buyer_headers,
            json={"conjugate": "APC", "clone": "PC61"},
        )
    )["item"]
    assert updated["conjugate"] == "APC"
    assert updated["clone"] == "PC61"


def test_antibody_metadata_available_to_any_signed_in_user(app_client, auth_headers):
    api_ok(
        app_client.post(
            "/api/users",
            headers=auth_headers,
            json={
                "username": "sampleonly",
                "password": "sample123",
                "display_name": "Sample Only",
                "role": "user",
                "permissions": {
                    "inventory.manage": True,
                    "inventory.search": True,
                    "inventory.view_reagents": False,
                    "inventory.view_samples": True,
                },
            },
        ),
        201,
    )
    login = api_ok(app_client.post("/api/login", json={"username": "sampleonly", "password": "sample123"}))
    sample_headers = {"Authorization": f"Bearer {login['token']}"}

    fetched = api_ok(app_client.get("/api/antibody-metadata?catalog_no=300412", headers=sample_headers))
    assert fetched["item"] is None

    created = api_ok(
        app_client.post(
            "/api/antibody-metadata",
            headers=sample_headers,
            json={"catalog_no": "300412", "target": "CD3"},
        ),
        201,
    )["item"]
    assert created["target"] == "CD3"

    updated = api_ok(
        app_client.patch(
            "/api/antibody-metadata?catalog_no=300412",
            headers=sample_headers,
            json={"conjugate": "FITC"},
        )
    )["item"]
    assert updated["conjugate"] == "FITC"

    app_client.cookies.clear()
    anonymous = app_client.get("/api/antibody-metadata?catalog_no=300412")
    assert anonymous.status_code == 401

    anonymous_create = app_client.post(
        "/api/antibody-metadata",
        json={"catalog_no": "300413", "target": "CD4"},
    )
    assert anonymous_create.status_code == 401
