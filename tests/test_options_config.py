import json

from services import options_config


def test_fixed_status_options_keep_required_values_before_custom_values():
    data = {
        "reagent_statuses": ["Available", "可用"],
        "validation_statuses": ["未验证", "Pending"],
        "sample_statuses": [],
    }

    clean = options_config.normalize_dropdown_options(data)

    assert clean["reagent_statuses"] == ["已订购", "可用", "停用", "已耗尽", "Available"]
    assert clean["validation_statuses"] == ["未验证", "通过", "不通过", "待复核", "Pending"]
    assert clean["sample_statuses"] == ["可用", "停用", "已耗尽"]
    assert clean["space_types"] == ["盒子", "冰箱", "液氮罐", "架子", "其他"]


def test_save_dropdown_options_persists_required_and_custom_status_options(monkeypatch, tmp_path):
    options_path = tmp_path / "dropdown_options.json"
    monkeypatch.setattr(options_config, "OPTIONS_CONFIG_PATH", options_path)

    saved = options_config.save_dropdown_options({
        "categories": ["抗体", "测试类型"],
        "brands": ["TestBrand"],
        "reagent_statuses": ["Available"],
        "validation_statuses": ["Pending"],
        "validation_methods": ["WB"],
        "sample_prefixes": ["SMP"],
        "sample_names": ["血清"],
        "amount_units": ["mL"],
        "sample_statuses": ["Available"],
    })

    assert saved["categories"] == ["抗体", "测试类型"]
    assert saved["reagent_statuses"] == ["已订购", "可用", "停用", "已耗尽", "Available"]
    assert saved["validation_statuses"] == ["未验证", "通过", "不通过", "待复核", "Pending"]
    assert saved["sample_statuses"] == ["可用", "停用", "已耗尽", "Available"]

    persisted = json.loads(options_path.read_text(encoding="utf-8-sig"))
    assert persisted["reagent_statuses"] == ["已订购", "可用", "停用", "已耗尽", "Available"]
    assert persisted["movement_merge_window_minutes"] == 30


def test_movement_merge_window_is_numeric_and_clamped():
    assert options_config.normalize_dropdown_options({"movement_merge_window_minutes": "45"})["movement_merge_window_minutes"] == 45
    assert options_config.normalize_dropdown_options({"movement_merge_window_minutes": "-5"})["movement_merge_window_minutes"] == 0
    assert options_config.normalize_dropdown_options({"movement_merge_window_minutes": "9999"})["movement_merge_window_minutes"] == 1440
    assert options_config.normalize_dropdown_options({"movement_merge_window_minutes": "bad"})["movement_merge_window_minutes"] == 30


def test_save_dropdown_options_preserves_hidden_status_groups(monkeypatch, tmp_path):
    options_path = tmp_path / "dropdown_options.json"
    monkeypatch.setattr(options_config, "OPTIONS_CONFIG_PATH", options_path)
    options_path.write_text(json.dumps({
        "reagent_statuses": ["已订购", "可用", "停用", "已耗尽", "借出"],
        "validation_statuses": ["未验证", "通过", "不通过", "待复核", "外送"],
        "sample_statuses": ["可用", "停用", "已耗尽", "待处理"],
    }, ensure_ascii=False), encoding="utf-8-sig")

    saved = options_config.save_dropdown_options({
        "categories": ["抗体"],
        "brands": ["TestBrand"],
        "validation_methods": ["WB"],
        "sample_prefixes": ["SMP"],
        "sample_names": ["血清"],
        "amount_units": ["mL"],
        "space_types": ["冷冻盒", "冰箱", "", "", "其他"],
    })

    assert saved["reagent_statuses"] == ["已订购", "可用", "停用", "已耗尽", "借出"]
    assert saved["validation_statuses"] == ["未验证", "通过", "不通过", "待复核", "外送"]
    assert saved["sample_statuses"] == ["可用", "停用", "已耗尽", "待处理"]


def test_space_type_options_are_limited_to_four_editable_slots_plus_other():
    clean = options_config.normalize_dropdown_options({
        "space_types": ["冷冻盒", "超低温冰箱", "液氮罐", "货架", "临时类型", "其他"],
    })

    assert clean["space_types"] == ["冷冻盒", "超低温冰箱", "液氮罐", "货架", "其他"]


def test_empty_space_type_slots_are_preserved_and_hidden_from_labels():
    clean = options_config.normalize_dropdown_options({
        "space_types": ["冷冻盒", "", "液氮罐", "", "其他"],
    })

    assert clean["space_types"] == ["冷冻盒", "", "液氮罐", "", "其他"]
    assert options_config.space_type_label(2, clean["space_types"]) == "类型 2"
    assert options_config.space_type_label(5, clean["space_types"]) == "其他"


def test_space_type_code_helper_accepts_only_slot_codes():
    assert options_config.clean_space_type_code("1") == 1
    assert options_config.clean_space_type_code("5") == 5
    try:
        options_config.clean_space_type_code("盒子")
    except ValueError:
        pass
    else:
        raise AssertionError("space type labels should not be accepted as stored values")


def test_space_type_label_falls_back_to_other_for_unexpected_stored_value():
    assert options_config.space_type_label("盒子") == "其他"
