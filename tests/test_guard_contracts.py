"""v1.6 B2：告警契约（contracts/guard.py）的闭集、映射与 serde 往返。"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from block_director.contracts import guard
from block_director.contracts.guard import (
    BODY_HEIGHT_BANDS,
    GUARD_SCHEMA_VERSION,
    HEAD_HEIGHT_BANDS,
    WARNING_TYPES,
    Confidence,
    GuardWarning,
    Severity,
    warning_type_problems,
)

ROOT = Path(__file__).resolve().parents[1]


def _sample(**overrides):
    payload = dict(shot_id="shot_004", frame_range=(1, 48),
                   type="framing_too_tight", subject="米迦尔",
                   evidence={"head_height_ratio": 0.93,
                             "expected_range": [0.55, 0.75], "lens_mm": 85},
                   severity=Severity.WARNING, confidence=Confidence.HIGH,
                   declared_intent="CU：面部特写",
                   suggestion_hint="拉远相机或降焦段")
    payload.update(overrides)
    return GuardWarning(**payload)


def test_schema_version_and_closed_set_match_tdd():
    assert GUARD_SCHEMA_VERSION == "guard/v1"
    #: 卡 V11 新增 safe_area_breach / element_collision 两个 warning 类型：
    #: 闭集从 16 扩到 18（唯一性断言原样保留，不是放宽）。
    assert len(WARNING_TYPES) == 18
    assert len(set(WARNING_TYPES)) == 18
    for required in ("framing_too_tight", "jump_cut_risk", "axis_screen_order",
                     "subject_behind_camera", "pace_monotony"):
        assert required in WARNING_TYPES


def test_unknown_type_is_reported_not_guessed():
    assert warning_type_problems("framing_too_tight") == ""
    problem = warning_type_problems("framing_bad")
    assert "framing_bad" in problem and "framing_too_tight" in problem
    assert _sample(type="framing_bad").problems()
    assert _sample().problems() == ""


def test_round_trip_is_lossless_through_json():
    original = _sample()
    restored = GuardWarning.from_dict(json.loads(json.dumps(original.to_dict(),
                                                            ensure_ascii=False)))
    assert restored.to_dict() == original.to_dict()
    assert restored.severity is Severity.WARNING
    assert restored.confidence is Confidence.HIGH
    assert restored.frame_range == (1, 48)


def test_string_enums_are_coerced_and_invalid_ones_raise():
    item = _sample(severity="error", confidence="low")
    assert item.severity is Severity.ERROR and item.confidence is Confidence.LOW
    with pytest.raises(ValueError):
        _sample(severity="fatal")


def test_band_tables_are_well_formed_and_split_by_measure():
    assert set(HEAD_HEIGHT_BANDS) == {"MCU", "CU", "ECU"}
    assert set(BODY_HEIGHT_BANDS) == {"MS", "MLS", "LS", "ELS"}
    assert not set(HEAD_HEIGHT_BANDS) & set(BODY_HEIGHT_BANDS)
    for lo, hi in [*HEAD_HEIGHT_BANDS.values(), *BODY_HEIGHT_BANDS.values()]:
        assert 0.0 <= lo < hi <= 1.0
    assert HEAD_HEIGHT_BANDS["CU"] == (0.55, 0.75)   # PRD D-12 的判据来源


@pytest.mark.parametrize("path", ["block_director/contracts/guard.py",
                                  "block_director/cinema/frustum_metrics.py"])
def test_pure_layer_never_imports_bpy(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    assert not names & {"bpy", "mathutils", "bpy_extras"}, names


def test_module_exports_its_public_names():
    for name in ("GuardWarning", "Severity", "Confidence", "WARNING_TYPES"):
        assert hasattr(guard, name)
