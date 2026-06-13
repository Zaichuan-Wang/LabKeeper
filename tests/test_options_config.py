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
