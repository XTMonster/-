"""E1：strict schema 转换（G2 判据 #8，卡 G8-E）。

守两件事：

1. ``to_strict`` 满足 DeepSeek strict 模式的硬约束（object 全量必填 ＋
   ``additionalProperties=false``），且可选字段改成**可空**而不是丢字段；
2. ``strip_nulls`` 与它严格互逆——真实 ``EMIT_SHOT_DRAFT_PARAMETERS`` 的合法入参，
   填满可选字段的 null（模拟 strict 输出）→ ``strip_nulls`` → 与原文
   ``json.dumps(sort_keys=True)`` 逐字节一致。
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import strict_schema as strict
from strict_schema import SCHEMA_KEYWORD_UNIVERSE, make_nullable, strip_nulls, to_strict

from block_director.layer5_orchestrator.editor import EMIT_SHOT_DRAFT_PARAMETERS
from block_director.layer5_orchestrator.tool_schema import validate_args


# --------------------------------------------------------------------------- #
# to_strict
# --------------------------------------------------------------------------- #
def test_to_strict_closes_every_object_and_requires_all_properties():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["a"],
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "integer"},
        },
    }
    out = to_strict(schema)
    assert out["additionalProperties"] is False
    assert out["required"] == ["a", "b"]
    # 原可选字段可空：模型"不想要"时写 null，而不是少键（strict 要求全键）。
    assert out["properties"]["b"]["type"] == ["integer", "null"]
    # 原必填字段保持原类型（不许变可空改变语义）。
    assert out["properties"]["a"]["type"] == "string"


def test_to_strict_nullable_rules_cover_enum_and_anyof():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {
            "enum_prop": {"type": "string", "enum": ["x", "y"]},
            "anyof_prop": {"anyOf": [{"type": "string"},
                                     {"type": "integer"}]},
            "union_prop": {"type": ["string", "integer"]},
        },
    }
    out = to_strict(schema)
    assert out["properties"]["enum_prop"]["enum"] == ["x", "y", None]
    assert out["properties"]["enum_prop"]["type"] == ["string", "null"]
    branches = out["properties"]["anyof_prop"]["anyOf"]
    assert branches[-1] == {"type": "null"}
    assert out["properties"]["union_prop"]["type"] == ["string", "integer", "null"]


def test_to_strict_recurses_through_items_and_nested_objects():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["rows"],
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["x"],
                    "properties": {
                        "x": {"type": "number", "minimum": 0},
                        "label": {"type": "string"},
                    },
                },
            },
        },
    }
    out = to_strict(schema)
    item = out["properties"]["rows"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["x", "label"]
    assert item["properties"]["x"]["minimum"] == 0
    assert item["properties"]["label"]["type"] == ["string", "null"]


def test_to_strict_transforms_anyof_branches_recursively():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["choice"],
        "properties": {
            "choice": {
                "anyOf": [
                    {"type": "object",
                     "properties": {"kind": {"type": "string", "const": "cat"},
                                    "lives": {"type": "integer"}},
                     "required": ["kind"], "additionalProperties": False},
                    {"type": "object",
                     "properties": {"kind": {"type": "string", "const": "dog"},
                                    "fetch": {"type": "boolean"}},
                     "required": ["kind"], "additionalProperties": False},
                ],
            },
        },
    }
    out = to_strict(schema)
    branches = out["properties"]["choice"]["anyOf"]
    assert len(branches) == 2  # choice 是必填键：不追加 null 分支
    cat, dog = branches
    assert cat["properties"]["kind"]["const"] == "cat"
    assert cat["required"] == ["kind", "lives"]
    assert cat["properties"]["lives"]["type"] == ["integer", "null"]
    assert dog["required"] == ["kind", "fetch"]
    assert dog["properties"]["fetch"]["type"] == ["boolean", "null"]


def test_to_strict_does_not_mutate_the_input():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["a"],
        "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
    }
    snapshot = copy.deepcopy(schema)
    to_strict(schema)
    assert schema == snapshot


def test_make_nullable_does_not_duplicate_the_null_branch():
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    out = make_nullable(schema)
    assert out["anyOf"] == [{"type": "string"}, {"type": "null"}]


def test_make_nullable_leaves_an_empty_schema_alone():
    # 空 schema 匹配一切（含 null），不需要也不能改写形状。
    assert make_nullable({}) == {}


def test_make_nullable_wraps_container_types_in_anyof_null():
    # DeepSeek strict（Beta）拒收含 array/object 的 type 联合：可空等价形状是
    # anyOf[原 schema, {"type": "null"}]，而不是 ["array","null"]。
    assert make_nullable({"type": "array", "items": {"type": "string"}}) == {
        "anyOf": [{"type": "array", "items": {"type": "string"}},
                  {"type": "null"}]}
    assert make_nullable({"type": "object"}) == {
        "anyOf": [{"type": "object"}, {"type": "null"}]}
    # 联合里只要含 array/object 就整体包 anyOf；标量联合才保留 type 联合。
    assert make_nullable({"type": ["string", "array"]}) == {
        "anyOf": [{"type": ["string", "array"]}, {"type": "null"}]}
    # 隐式 object（没写 type、只有 properties）同样包 anyOf。
    assert make_nullable({"properties": {"k": {"type": "string"}}}) == {
        "anyOf": [{"properties": {"k": {"type": "string"}}},
                  {"type": "null"}]}


def test_to_strict_wraps_optional_arrays_and_objects_in_anyof_null():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id"],
        "properties": {
            "id": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "meta": {"type": "object", "additionalProperties": False,
                     "required": ["n"],
                     "properties": {"n": {"type": "integer"},
                                    "note": {"type": "string"}}},
            "label": {"type": "string"},
        },
    }
    out = to_strict(schema)
    assert out["properties"]["tags"] == {
        "anyOf": [{"type": "array", "items": {"type": "string"}},
                  {"type": "null"}]}
    assert out["properties"]["meta"] == {
        "anyOf": [{
            "type": "object",
            "additionalProperties": False,
            "required": ["n", "note"],
            "properties": {"n": {"type": "integer"},
                           "note": {"type": ["string", "null"]}},
        }, {"type": "null"}]}
    # 标量可空仍是 type 联合，不是 anyOf 包。
    assert out["properties"]["label"]["type"] == ["string", "null"]


# --------------------------------------------------------------------------- #
# strip_nulls
# --------------------------------------------------------------------------- #
def test_strip_nulls_removes_optional_nulls_and_keeps_required_nulls():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id"],
        "properties": {"id": {"type": "string"}, "note": {"type": "string"}},
    }
    args = {"id": None, "note": None}
    strip_nulls(args, schema)
    assert args == {"id": None}  # 必填键的 null 保留；可选键被剥掉


def test_strip_nulls_recurses_into_arrays_and_nested_objects():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["rows"],
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["x"],
                    "properties": {"x": {"type": "number"},
                                   "label": {"type": "string"}},
                },
            },
        },
    }
    args = {"rows": [{"x": 1, "label": None}, {"x": None, "label": "L"}]}
    strip_nulls(args, schema)
    assert args == {"rows": [{"x": 1}, {"x": None, "label": "L"}]}


def test_strip_nulls_recurses_into_the_matching_anyof_branch():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["choice"],
        "properties": {
            "choice": {
                "anyOf": [
                    {"type": "object",
                     "properties": {"kind": {"type": "string", "const": "cat"},
                                    "lives": {"type": "integer"}},
                     "required": ["kind"], "additionalProperties": False},
                    {"type": "object",
                     "properties": {"kind": {"type": "string", "const": "dog"},
                                    "fetch": {"type": "boolean"}},
                     "required": ["kind"], "additionalProperties": False},
                ],
            },
        },
    }
    args = {"choice": {"kind": "cat", "lives": None}}
    strip_nulls(args, schema)
    assert args == {"choice": {"kind": "cat"}}


def test_strip_nulls_does_not_mutate_scalar_values():
    schema = {"type": "array", "items": {"type": "string"}}
    args = ["a", None]
    strip_nulls(args, schema)
    # array 元素不是 dict：没有"可选键"可剥，null 项原样保留。
    assert args == ["a", None]


def test_roundtrip_optional_array_object_and_anyof_are_byte_identical():
    """三种 nullable 编码（anyOf 包 array / anyOf 包 object / anyOf 追加 null）
    都要与 strip_nulls 严格互逆：填 null → 剥 null → 逐字节还原。"""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id"],
        "properties": {
            "id": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "meta": {"type": "object", "additionalProperties": False,
                     "required": ["n"],
                     "properties": {"n": {"type": "integer"},
                                    "note": {"type": "string"}}},
            "choice": {"anyOf": [
                {"type": "string"},
                {"type": "object", "additionalProperties": False,
                 "required": ["x"],
                 "properties": {"x": {"type": "number"}}},
            ]},
        },
    }
    full = {"id": "a", "tags": ["t1"], "meta": {"n": 1},
            "choice": {"x": 2.5}}
    assert validate_args(schema, full) == []
    filled = _fill_optional_nulls(copy.deepcopy(full), schema)
    stripped = strip_nulls(filled, schema)
    assert json.dumps(stripped, sort_keys=True) == \
        json.dumps(full, sort_keys=True)

    # 全 null 的形状（strict 全键必填时模型"不想要"的写法）也要剥回最小形状。
    minimal = {"id": "a"}
    assert validate_args(schema, minimal) == []
    filled_min = _fill_optional_nulls(copy.deepcopy(minimal), schema)
    assert filled_min == {"id": "a", "tags": None, "meta": None,
                          "choice": None}
    stripped_min = strip_nulls(filled_min, schema)
    assert json.dumps(stripped_min, sort_keys=True) == \
        json.dumps(minimal, sort_keys=True)


# --------------------------------------------------------------------------- #
# 真实 EMIT_SHOT_DRAFT_PARAMETERS 的往返属性
# --------------------------------------------------------------------------- #
def _fill_optional_nulls(args: Any, schema: Dict[str, Any]) -> Any:
    """模拟 strict 输出：把原 schema 里每个可选键补成 null（全键必填）。"""
    if isinstance(args, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for item in args:
                _fill_optional_nulls(item, items)
        return args
    if not isinstance(args, dict):
        return args
    target = schema
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        branch = strict.matching_any_of_branch(any_of, args)
        if branch is not None:
            target = branch
    required = set(target.get("required") or [])
    properties = target.get("properties") or {}
    for key, prop in properties.items():
        if isinstance(prop, dict) and key not in required and key not in args:
            args[key] = None
    for key, value in list(args.items()):
        prop = properties.get(key)
        if isinstance(prop, dict):
            _fill_optional_nulls(value, prop)
    return args


def _roundtrip(args: Dict[str, Any]) -> Dict[str, Any]:
    problems = validate_args(EMIT_SHOT_DRAFT_PARAMETERS, args)
    assert problems == [], f"样本必须先通过原 schema 校验：{problems}"
    filled = _fill_optional_nulls(copy.deepcopy(args),
                                  EMIT_SHOT_DRAFT_PARAMETERS)
    stripped = strip_nulls(filled, EMIT_SHOT_DRAFT_PARAMETERS)
    return stripped


def test_roundtrip_minimal_draft_is_byte_identical():
    original = {"shot_id": "shot_001"}
    stripped = _roundtrip(original)
    assert json.dumps(stripped, sort_keys=True) == \
        json.dumps(original, sort_keys=True)


def test_roundtrip_full_draft_is_byte_identical():
    original = {
        "shot_id": "shot_001",
        "shot_type": "MCU",
        "characters": ["伊恩"],
        "actions": [
            {"character_id": "伊恩", "action_type": "walk_to",
             "start_frame": 1, "end_frame": 24,
             "target_position": [1.0, 2.0, 0.0],
             "params": {"speed": "walk"}},
        ],
        "dialogues": [
            {"character_id": "伊恩", "text": "……",
             "start_frame": 10, "end_frame": 20},
        ],
        "camera": {
            "side": "front_left",
            "lens": 35.0,
            "movements": [
                {"type": "dolly_in", "amount": 2.0, "start_frame": 1,
                 "end_frame": 24, "seed": 0, "subject": "伊恩"},
            ],
        },
        "gaze": [{"from": "伊恩", "to": "镜头"}],
        "vfx": [
            {"id": "fx_1", "type": "smoke", "position": [0, 0, 0],
             "size": [1, 1, 1], "start_frame": 1, "end_frame": 12},
        ],
        "beats": [
            {"t": 0.1, "subject": "伊恩", "verb": "walk_to", "target": "摊位",
             "face_to": "screen_left", "pace": "normal", "curve": "sharp",
             "react": ""},
        ],
        "composition": {"rule": "thirds", "subject_position": "left_third"},
        "rule_justifications": [
            {"rule": "R001", "action": "follow", "reason": "", "precedent": ""},
        ],
        "prompt": "伊恩走到摊位前。",
    }
    stripped = _roundtrip(original)
    assert json.dumps(stripped, sort_keys=True, ensure_ascii=False) == \
        json.dumps(original, sort_keys=True, ensure_ascii=False)


def test_roundtrip_real_schema_with_every_optional_field_null_is_byte_identical():
    """真实 schema 的 strict 形状：所有可选 array/object 都是 anyOf+null，
    全 null 填充后 strip_nulls 必须逐字节还原最小形状。"""
    original = {"shot_id": "shot_001"}
    filled = _fill_optional_nulls(copy.deepcopy(original),
                                  EMIT_SHOT_DRAFT_PARAMETERS)
    assert "characters" in filled and filled["characters"] is None
    assert "camera" in filled and filled["camera"] is None
    stripped = strip_nulls(filled, EMIT_SHOT_DRAFT_PARAMETERS)
    assert json.dumps(stripped, sort_keys=True) == \
        json.dumps(original, sort_keys=True)

    strict_schema = to_strict(EMIT_SHOT_DRAFT_PARAMETERS)
    characters = strict_schema["properties"]["characters"]
    assert characters["anyOf"][0]["type"] == "array"
    assert characters["anyOf"][-1] == {"type": "null"}
    camera = strict_schema["properties"]["camera"]
    assert camera["anyOf"][0]["type"] == "object"
    assert camera["anyOf"][-1] == {"type": "null"}


def _schema_keywords(schema: Dict[str, Any]) -> set:
    found: set = set()
    stack: List[Dict[str, Any]] = [schema]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if key in SCHEMA_KEYWORD_UNIVERSE or key in (
                    "minLength", "maxLength", "pattern", "format",
                    "multipleOf", "$def", "$ref"):
                found.add(key)
            if isinstance(value, dict):
                stack.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        stack.append(item)
    return found


def test_keyword_universe_covers_the_real_schema_and_its_strict_form():
    used = _schema_keywords(EMIT_SHOT_DRAFT_PARAMETERS)
    used |= _schema_keywords(to_strict(EMIT_SHOT_DRAFT_PARAMETERS))
    # "null" 是能力位：strict 转换会产出它；原 schema 不会写它。
    used.discard("$def")
    used.discard("$ref")
    missing = sorted(used - set(SCHEMA_KEYWORD_UNIVERSE))
    assert not missing, (
        f"sidecar 启动门的关键字全集漏了真实 schema 用的 {missing}"
    )


def _walk_pairs(original: Dict[str, Any], strict_schema: Dict[str, Any],
                path: str, problems: List[str]) -> None:
    """原/strict 两份 schema 并行走：钉 strict 形状不变量。"""
    if strict_schema.get("type") == "object" or "properties" in strict_schema:
        props = strict_schema.get("properties") or {}
        if strict_schema.get("additionalProperties") is not False:
            problems.append(f"{path} additionalProperties != false")
        if list(props.keys()) != list(strict_schema.get("required") or []):
            problems.append(f"{path} required != 全部 properties")
        original_required = set(original.get("required") or [])
        for key, sub in props.items():
            original_sub = (original.get("properties") or {}).get(key, {})
            if key not in original_required and isinstance(sub, dict):
                nullable = False
                if isinstance(sub.get("type"), list) and "null" in sub["type"]:
                    nullable = True
                if isinstance(sub.get("enum"), list) and None in sub["enum"]:
                    nullable = True
                if any(branch == {"type": "null"}
                       for branch in (sub.get("anyOf") or [])
                       if isinstance(branch, dict)):
                    nullable = True
                if sub == {}:
                    nullable = True
                if not nullable:
                    problems.append(f"{path}.{key} 可选但不可空")
            _walk_pairs(original_sub if isinstance(original_sub, dict) else {},
                        sub if isinstance(sub, dict) else {},
                        f"{path}.{key}", problems)
    if isinstance(strict_schema.get("items"), dict):
        _walk_pairs(original.get("items") or {},
                    strict_schema["items"], f"{path}[]", problems)
    for branch_o, branch_s in zip(original.get("anyOf") or [],
                                  strict_schema.get("anyOf") or []):
        if isinstance(branch_o, dict) and isinstance(branch_s, dict):
            _walk_pairs(branch_o, branch_s, f"{path}[anyOf]", problems)


def test_strict_form_of_the_real_schema_holds_every_invariant():
    problems: List[str] = []
    _walk_pairs(EMIT_SHOT_DRAFT_PARAMETERS,
                to_strict(EMIT_SHOT_DRAFT_PARAMETERS), "args", problems)
    assert not problems, problems
