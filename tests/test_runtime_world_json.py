"""R11（T4）：运行时世界坐标 JSON 的一致性契约（纯层，禁止 import bpy）。

判据：
1. schema 版本化（``runtime-world/v1``）；
2. ``floats_close`` 按 1e-4 容差判定（同口径、差 2e-4 拒）；
3. ``divergence_report`` 对 characters/cameras/props 三表逐 id 逐键比对，
   给出带路径的差值清单；一致时为空表；
4. ``E_WORLD_STATE_DIVERGED`` 错误码是常量的单一真源。
"""

from __future__ import annotations

from block_director.contracts.world_state import (
    E_WORLD_STATE_DIVERGED,
    RUNTIME_WORLD_STATE_FILENAME,
    WORLD_STATE_SCHEMA_VERSION,
    divergence_report,
    floats_close,
    normalize_world_state,
    world_state_fingerprint,
    world_state_target_path,
)


def test_schema_version_is_pinned():
    assert WORLD_STATE_SCHEMA_VERSION == "runtime-world/v1"


def test_filename_is_pinned():
    assert RUNTIME_WORLD_STATE_FILENAME == "runtime_world_state.json"


def test_target_path_derives_from_audit_dir(tmp_path):
    #: 审计目录是 <运行根>/runs；JSON 与其同级、落在运行根目录（R11 的
    #: “运行时可取”位置），由驱动器在构建成功后登记并刷新。
    assert (world_state_target_path(tmp_path / "runs")
            == tmp_path / "runtime_world_state.json")


def test_target_path_none_when_no_audit_dir():
    assert world_state_target_path(None) is None
    assert world_state_target_path("") is None


def test_floats_close_tolerance():
    assert floats_close([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) is True
    #: 1e-5 差在 1e-4 容差内
    assert floats_close([1.0], [1.00001]) is True
    #: 2e-4 差超容差
    assert floats_close([1.0], [1.0002]) is False
    #: 长度不同必拒
    assert floats_close([1.0, 2.0], [1.0]) is False


def test_divergence_report_empty_when_identical():
    payload = {
        "characters": {"char_001": {"position": [1.0, 2.0, 3.0]}},
        "cameras": {"shot_001": {"position": [0.0, 0.0, 1.5],
                                 "lens_mm": 50.0}},
        "props": {},
    }
    live = {
        "characters": {"char_001": {"position": [1.00001, 2.0, 3.0]}},
        "cameras": {"shot_001": {"position": [0.0, 0.0, 1.50001],
                                 "lens_mm": 50.0}},
        "props": {},
    }
    assert divergence_report(payload, live) == []


def test_divergence_report_lists_each_drift():
    payload = {
        "characters": {"char_001": {"position": [1.0, 2.0, 3.0]}},
        "cameras": {"shot_001": {"position": [0.0, 0.0, 1.5],
                                 "lens_mm": 50.0}},
        "props": {"silver_coin": {"position": [5.0, 5.0, 0.0]}},
    }
    live = {
        "characters": {"char_001": {"position": [1.0, 2.5, 3.0]}},
        "cameras": {"shot_001": {"position": [0.0, 0.0, 1.5],
                                 "lens_mm": 52.0}},
        "props": {"silver_coin": {"position": [5.0, 5.0, 0.0]}},
    }
    report = divergence_report(payload, live)
    paths = {item["path"] for item in report}
    assert paths == {"characters.char_001.position",
                     "cameras.shot_001.lens_mm"}
    entry = next(item for item in report
                 if item["path"] == "characters.char_001.position")
    assert entry["max_delta"] > 1e-4
    assert entry["actual"] == [1.0, 2.5, 3.0]
    assert entry["expected"] == [1.0, 2.0, 3.0]


def test_divergence_code_is_single_source():
    assert E_WORLD_STATE_DIVERGED == "E_WORLD_STATE_DIVERGED"


def test_world_state_fingerprint_treats_negative_zero_as_zero():
    expected = {
        "characters": {
            "甲": {
                "position": [2.0, -1.0, 0.0],
                "facing": [1.0, 0.0, 0.0],
            },
        },
    }
    observed = {
        "characters": {
            "甲": {
                "position": [2.0, -1.0, -0.0],
                "facing": [1.0, -0.0, 0.0],
            },
        },
    }

    assert normalize_world_state(observed) == expected
    assert world_state_fingerprint(observed) == world_state_fingerprint(expected)


def test_world_state_fingerprint_keeps_nonzero_differences_exact():
    first = {"characters": {"甲": {"position": [0.0, 0.0, 0.0]}}}
    second = {"characters": {"甲": {"position": [0.0, 1e-7, 0.0]}}}

    assert world_state_fingerprint(first) != world_state_fingerprint(second)
