"""卡 A5：目标模型规格表（v1.7 TDD §12.1）。"""

from __future__ import annotations

from block_director.contracts.config import AppConfig
from block_director.contracts.enums import Severity
from block_director.contracts.target_models import (
    RANGE_KEYS,
    TargetModelError,
    load_table,
)


def test_three_models_load():
    table = load_table()
    assert set(table) == {"seedance_2.5", "kling", "hailuo_h3"}
    assert all(spec.label for spec in table.values())


def test_ranges_valid():
    for spec in load_table().values():
        for key in RANGE_KEYS:
            if key in spec.raw:
                low, high = spec.raw[key]
                assert low < high, (spec.label, key)


def test_missing_file_raises():
    try:
        load_table(path="no_such_target_models.yaml")
    except TargetModelError:
        return
    raise AssertionError("缺文件应当抛 TargetModelError")


def test_missing_label_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("model_x:\n  foo: 1\n", encoding="utf-8")
    try:
        load_table(path=path)
    except TargetModelError:
        return
    raise AssertionError("缺 label 应当抛 TargetModelError")


def test_bad_range_raises(tmp_path):
    path = tmp_path / "bad_range.yaml"
    path.write_text(
        "model_x:\n  label: X\n  aspect_range: [2.0, 1.0]\n",
        encoding="utf-8")
    try:
        load_table(path=path)
    except TargetModelError:
        return
    raise AssertionError("区间非法应当抛 TargetModelError")


def test_cfg172():
    config = AppConfig()
    config.delivery.target_model = "unknown_x"
    issues = [issue for issue in config.validate()
              if issue.code == "CFG_172"]
    assert len(issues) == 1
    assert issues[0].severity is Severity.WARNING
