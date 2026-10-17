"""空间尺观测契约纯 Python 层测试（Ticket 01 纯接口）。

覆盖：
1. DTO 与 JSON 双向 round-trip：从样例 JSON 实例化、再序列化，逐字段一致，
   且序列化结果仍通过 ``.scratch/`` 下的 jsonschema 校验；
2. ``validate_bundle`` 对合法 bundle 返回空发现，对坏 bundle 给出可定位发现：
   未知处方操作 / 悬空测量引用 / 非法来源 / 缺数值对；
3. 常量（处方 allow-list、来源四态）与契约/既有测试保持一致。
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from block_director.contracts.spatial_ruler import (
    PRESCRIPTION_OPERATIONS,
    PROVENANCE_STATES,
    ObservationBundle,
    validate_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
RULER_DIR = ROOT / ".scratch" / "spatial-ruler-json"
SCHEMA = RULER_DIR / "schema" / "spatial-ruler-observation.v1.schema.json"
EXAMPLE = RULER_DIR / "examples" / "dock-market-observation.v2.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _example() -> dict:
    return _load(EXAMPLE)


def test_example_round_trips_through_dtos() -> None:
    bundle = ObservationBundle.from_dict(_example())
    rebuilt = bundle.to_dict()
    assert rebuilt == _example()
    jsonschema.validate(instance=rebuilt, schema=_load(SCHEMA))


def test_dto_field_survival() -> None:
    source = _example()
    bundle = ObservationBundle.from_dict(source)
    assert bundle.schema_version == "spatial-ruler-observation/v2"
    assert len(bundle.measurements) == len(source["measurements"])
    assert len(bundle.verdicts) == len(source["verdicts"])
    assert len(bundle.prescriptions) == len(source["prescriptions"])
    first = bundle.measurements[0]
    assert first.measurement_id == "m_total_duration"
    assert first.source == first.provenance == "script_declaration"


def test_validate_accepts_example() -> None:
    assert validate_bundle(_example()) == []


def test_validate_rejects_unknown_prescription_operation() -> None:
    data = _example()
    data["prescriptions"][0]["operation"] = "teleport_actor"
    findings = validate_bundle(data)
    assert any(f["code"] == "unknown_operation" for f in findings)
    assert any("teleport_actor" in f["message"] for f in findings)


def test_validate_rejects_dangling_measurement_refs() -> None:
    data = _example()
    for verdict in data["verdicts"]:
        if verdict.get("evidence"):
            verdict["evidence"] = ["m_no_such_measurement"]
            break
    else:
        raise AssertionError("样例缺少带 evidence 的 verdict")
    findings = validate_bundle(data)
    assert any(f["code"] == "dangling_reference" for f in findings)


def test_validate_rejects_illegal_provenance() -> None:
    data = _example()
    data["measurements"][0]["provenance"] = "hearsay"
    data["measurements"][0]["source"] = "hearsay"
    findings = validate_bundle(data)
    assert any(f["code"] == "illegal_provenance" for f in findings)


def test_validate_rejects_missing_numeric_pairs() -> None:
    data = _example()
    for verdict in data["verdicts"]:
        if verdict.get("rule_code") == "SR002":
            verdict.pop("actual", None)
            break
    else:
        raise AssertionError("样例缺少 SR002 判定")
    findings = validate_bundle(data)
    assert any(f["code"] == "verdict_missing_numeric_pair" for f in findings)


def test_allow_list_constants_match_contract() -> None:
    assert PRESCRIPTION_OPERATIONS == {
        "retime_shot", "restore_cast", "reframe", "move_character",
        "change_camera_side", "review_transition"}
    assert {"script_declaration", "plan_intent",
            "algorithmic_measurement", "blender_geometry"} == PROVENANCE_STATES
