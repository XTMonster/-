"""§7.5 工具参数校验器测试（零依赖的 JSON Schema 子集）。"""

from __future__ import annotations

from block_director.layer5_orchestrator.planner import EMIT_PLAN_TOOL_PARAMETERS
from block_director.layer5_orchestrator.tool_schema import validate_args


def _plan(**overrides):
    shot = {"shot_id": "shot_001", "intent": "建立场景",
            "shot_type": "MS", "duration_frames": 96}
    shot.update(overrides)
    return {"shots": [shot]}


def test_valid_plan_passes():
    assert validate_args(EMIT_PLAN_TOOL_PARAMETERS, _plan()) == []


def test_missing_required_field_is_reported():
    payload = {"shots": [{"shot_id": "s1", "intent": "x"}]}
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, payload)
    assert any("shot_type" in p for p in problems)
    assert any("duration_frames" in p for p in problems)


def test_enum_is_enforced():
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, _plan(shot_type="XXXL"))
    assert any("取值必须是" in p for p in problems)


def test_minimum_is_enforced():
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, _plan(duration_frames=0))
    assert any("不得小于" in p for p in problems)


def test_maximum_is_enforced():
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, _plan(duration_frames=9999))
    assert any("不得大于" in p for p in problems)


def test_type_is_enforced():
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, _plan(duration_frames="96"))
    assert any("类型应为" in p for p in problems)


def test_bool_is_not_accepted_as_integer():
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, _plan(duration_frames=True))
    assert any("类型应为" in p for p in problems)


def test_empty_shots_rejected():
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, {"shots": []})
    assert any("至少需要" in p for p in problems)


def test_unknown_field_rejected_when_additional_properties_false():
    problems = validate_args(EMIT_PLAN_TOOL_PARAMETERS, _plan(bogus=1))
    assert any("不允许出现字段" in p for p in problems)


def test_union_type_allows_null():
    schema = {"type": "object",
              "properties": {"note": {"type": ["string", "null"]}}}
    assert validate_args(schema, {"note": None}) == []
    assert validate_args(schema, {"note": "ok"}) == []
    assert validate_args(schema, {"note": 5})
