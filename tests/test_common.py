"""通用工具测试。"""

from core.common import clean_int_range, clean_optional_positive_int


def test_clean_int_range_defaults_and_bounds():
    assert clean_int_range("", default=2, minimum=1, maximum=300) == 2
    assert clean_int_range(None, default=2, minimum=1, maximum=300) == 2
    assert clean_int_range("bad", default=2, minimum=1, maximum=300) == 2
    assert clean_int_range(0, default=2, minimum=1, maximum=300) == 1
    assert clean_int_range(999, default=2, minimum=1, maximum=300) == 300
    assert clean_int_range("3.7", default=2, minimum=1, maximum=300) == 3


def test_clean_optional_positive_int():
    assert clean_optional_positive_int("") is None
    assert clean_optional_positive_int(None) is None
    assert clean_optional_positive_int("bad") is None
    assert clean_optional_positive_int(0) is None
    assert clean_optional_positive_int(-1) is None
    assert clean_optional_positive_int("3.7") == 3
    assert clean_optional_positive_int(999, maximum=20) == 20
