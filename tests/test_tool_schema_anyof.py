"""G2 判据 #8 / 卡 G8-A：零依赖 JSON Schema 校验器的 ``const`` 与 ``anyOf``。

``anyOf`` 的全部失败报告按三条规则选分支：

1. 判别式：所有 object 分支含同一个 ``const`` 键 ``k`` 且值为携带 ``k`` 的
   dict → 报 ``value[k]`` 命中的那一个分支，路径后缀 ``（k=value[k]）``；
2. 判别式值未命中 → ``{path}.{k} 取值必须是 [全部 const] 之一，实际 {v!r}``；
3. 无判别式 → 报错误最少的那个分支，前缀 ``{path} 不匹配任何允许形状：``。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.layer5_orchestrator.tool_schema import validate_args  # noqa: E402


#: 双分支判别式样例：``action_type`` 决定走哪一支（后续卡会把草案的
#: ``actions[].items`` 渲染成这个形状，用于逐动作收窄参数键表）。
_ACTION_UNION = {
    "anyOf": [
        {
            "type": "object",
            "required": ["action_type", "to"],
            "properties": {
                "action_type": {"const": "look_at"},
                "to": {"type": "string"},
            },
        },
        {
            "type": "object",
            "required": ["action_type", "target_position"],
            "properties": {
                "action_type": {"const": "walk_to"},
                "target_position": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {"type": "number"},
                },
            },
        },
    ],
}


def test_const_passes_when_value_matches():
    schema = {"const": 42}
    assert validate_args(schema, 42) == []


def test_const_fails_and_names_both_values():
    problems = validate_args({"const": 42}, 7)
    assert problems == ["args 取值必须是 42，实际 7"]


def test_const_does_not_treat_bool_as_number():
    """与既有类型纪律一致：``const: 1`` 不得接受 ``true``。"""
    problems = validate_args({"const": 1}, True)
    assert problems == ["args 取值必须是 1，实际 True"]


def test_const_null_present_accepts_none_and_rejects_zero():
    """``const`` 键存在性检查：``{"const": null}`` 不能被静默忽略。"""
    assert validate_args({"const": None}, None) == []
    problems = validate_args({"const": None}, 0)
    assert problems == ["args 取值必须是 None，实际 0"]


def test_const_true_rejects_number_one():
    """``const: True`` 不得接受 ``1``（bool 与 number 的对称方向）。"""
    problems = validate_args({"const": True}, 1)
    assert problems == ["args 取值必须是 True，实际 1"]


def test_const_null_and_structured_values():
    assert validate_args({"const": None}, None) == []
    assert validate_args({"const": [1, 2, 3]}, [1, 2, 3]) == []
    assert validate_args({"const": {"x": 1}}, {"x": 1}) == []


def test_anyof_passes_when_any_branch_matches():
    assert validate_args(
        _ACTION_UNION, {"action_type": "look_at", "to": "char_002"}) == []
    assert validate_args(
        _ACTION_UNION,
        {"action_type": "walk_to", "target_position": [1.0, 2.0, 0.0]}) == []


def test_discriminator_names_the_action_and_the_bad_key():
    problems = validate_args(_ACTION_UNION, {"action_type": "look_at"})
    assert problems == ["args（action_type=look_at） 缺少必填字段 to"]


def test_unknown_discriminator_lists_all_consts():
    problems = validate_args(_ACTION_UNION, {"action_type": "dance"})
    assert problems == [
        "args.action_type 取值必须是 ['look_at', 'walk_to'] 之一，实际 'dance'",
    ]


def test_fewest_problems_branch_is_chosen_without_discriminator():
    """无判别式时只报错误最少的那个分支（1 个 missing 对 2 个 missing）。"""
    schema = {
        "anyOf": [
            {"type": "object", "required": ["a"],
             "properties": {"a": {"type": "string"}}},
            {"type": "object", "required": ["a", "b"],
             "properties": {"a": {"type": "string"}, "b": {"type": "string"}}},
        ],
    }
    problems = validate_args(schema, {})
    assert problems
    assert problems[0] == "args 不匹配任何允许形状"
    assert any("a" in p and "b" not in p for p in problems[1:])


def test_anyof_nested_inside_array_items():
    schema = {
        "type": "array",
        "items": _ACTION_UNION,
    }
    problems = validate_args(schema, [{"action_type": "look_at"}])
    assert problems == ["args[0]（action_type=look_at） 缺少必填字段 to"]


def test_number_or_point_union():
    schema = {
        "anyOf": [
            {"type": "number"},
            {
                "type": "object",
                "required": ["point"],
                "properties": {
                    "point": {
                        "type": "array",
                        "minItems": 3,
                        "maxItems": 3,
                        "items": {"type": "number"},
                    },
                },
            },
        ],
    }
    assert validate_args(schema, 15) == []
    assert validate_args(schema, {"point": [1, 2, 0]}) == []
    assert validate_args(schema, "screen_left")
    assert validate_args(schema, {"point": [1, 2]})
