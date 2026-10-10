"""provider strict function calling 的 schema 转换（G2 判据 #8，卡 G8-E 的 E1）。

DeepSeek strict 模式（Beta，https://api-docs.deepseek.com/guides/tool_calls）的硬约束：

- 端点必须是 ``https://api.deepseek.com/beta/chat/completions``；
- 每个 function 都要 ``strict: true``；
- **每个 object 的所有 properties 都必须进 ``required``**，且
  ``additionalProperties=false``；
- 服务端会校验 JSON Schema：含不支持的写法/关键字会直接返回错误。

"可选字段"在 strict 模式下无法用"不在 required 里"表达（required 必须列全）。于是
把可选字段改成**可空**（nullable）是唯一不改语义的等价形状：模型"不想要"该字段时
输出 ``null``，sidecar 收包时再用 :func:`strip_nulls` 按**原 schema** 把可选键剥掉，
恢复原状。GitHub deepseek-ai/DeepSeek-V3 issue #1069 记录过 strict 模式下
``function.arguments`` 偶发坏 JSON（键名缺引号），所以探针要单独量
``malformed_rate``，本模块不做任何容错改写。

本模块是纯函数：不导入 ``bpy``、不导入 ``block_director``，可被 sidecar、探针与
pytest 三方共用（单一真源）。

"可空"有两种**等价编码**（2026-10-10 实测决定，DeepSeek beta）：

- 标量类型（string/number/integer/boolean）用 type 联合 ``["<type>", "null"]``；
- 类型是（或含）array/object 的字段、以及**本来就是 anyOf** 的字段，用
  ``{"anyOf": [<原 schema>, {"type": "null"}]}``。DeepSeek beta 拒收含
  array/object 的 type 联合（400 ``unknown variant `array``）——
  ``docs/evidence/20261010-015527-strict-probe/strict_probe.json`` 的
  ``null_array``/``null_object`` 变体三次全 400，而 anyOf 三次全 200。
  两种形状对校验器等价，语义一字不变；``strip_nulls`` 按**原 schema** 剥键，
  所以与编码无关。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 本仓工具 schema 会用到的、以及 strict 转换会产出的 JSON Schema 关键字全集。
#: ``tools/probe_strict_tools.py`` 逐条实测提供方是否支持；sidecar 启动门要求
#: 探针的 ``supported_keywords`` 覆盖这里每一个。``null`` 是"可空类型"能力位
#: （strict 转换给可选字段加的 ``["<type>", "null"]`` / ``enum+None`` /
#: ``anyOf+{"type":"null"}`` 全靠它），不是关键字，但一样要被实测覆盖。
SCHEMA_KEYWORD_UNIVERSE: Tuple[str, ...] = (
    "additionalProperties",
    "anyOf",
    "const",
    "enum",
    "items",
    "maximum",
    "maxItems",
    "minimum",
    "minItems",
    "null",
    "properties",
    "required",
    "type",
)


def _is_object(schema: Dict[str, Any]) -> bool:
    return schema.get("type") == "object" or "properties" in schema


def _add_null_type(types: Sequence[str]) -> List[str]:
    out = list(types)
    if "null" not in out:
        out.append("null")
    return out


def _type_contains_container(raw_type: Any) -> bool:
    """type 是/含 ``array`` 或 ``object``：不能进 DeepSeek strict 的 type 联合。"""
    if raw_type == "array" or raw_type == "object":
        return True
    return isinstance(raw_type, list) and (
        "array" in raw_type or "object" in raw_type)


def _is_implicit_object(schema: Dict[str, Any]) -> bool:
    """没写 ``type``、只有 ``properties`` 的隐式 object schema。"""
    return "type" not in schema and isinstance(schema.get("properties"), dict)


def make_nullable(schema: Dict[str, Any]) -> Dict[str, Any]:
    """把一段属性 schema 改成"原值或 null"；只用于**原 schema 里的可选字段**。

    规则（卡 G8-E，2026-10-10 修订）：

    - **本来就是 anyOf**：追加一个 ``{"type": "null"}`` 分支；
    - **type 是/含 array/object（或隐式 object）**：整体包成
      ``{"anyOf": [<原 schema>, {"type": "null"}]}``——DeepSeek strict（Beta）
      拒收含 array/object 的 type 联合，这是等价的"可空"编码，不是改形状；
    - **标量 type**（string/number/integer/boolean）：保留 type 联合
      ``[type, "null"]``；``enum`` 追加 ``None``。

    输入不被改动（返回新对象）。
    """
    out = dict(schema)
    if "anyOf" in out and isinstance(out["anyOf"], list):
        branches = [dict(branch) for branch in out["anyOf"]]
        already_null = any(set(branch) == {"type"} and branch.get("type") == "null"
                           for branch in branches)
        if not already_null:
            branches.append({"type": "null"})
        out["anyOf"] = branches
        return out
    raw_type = out.get("type")
    if _type_contains_container(raw_type) or _is_implicit_object(out):
        # array/object 不能进 type 联合（DeepSeek beta 400 unknown variant）：
        # 等价的"可空"形状是 anyOf[原 schema, {"type": "null"}]。
        return {"anyOf": [out, {"type": "null"}]}
    if "enum" in out:
        values = list(out["enum"])
        if None not in values:
            values.append(None)
        out["enum"] = values
    if "type" in out:
        if isinstance(raw_type, str):
            out["type"] = _add_null_type([raw_type])
        elif isinstance(raw_type, list):
            out["type"] = _add_null_type(raw_type)
    # 空 schema（``{}``）本来就匹配一切（含 null），原样保留即可。
    return out


def to_strict(schema: Dict[str, Any]) -> Dict[str, Any]:
    """递归把 schema 转成 strict 形状；输入不被改动（返回新对象）。

    - 每个 object：``additionalProperties=false``、``required`` 列全所有 properties；
    - 原 schema 里可选的属性改成可空（:func:`make_nullable`）；
    - ``anyOf`` 分支、``items``、``$def`` 递归转换，``const`` 原样保留。
    """
    out = dict(schema)
    if isinstance(out.get("anyOf"), list):
        out["anyOf"] = [to_strict(branch) if isinstance(branch, dict) else branch
                        for branch in out["anyOf"]]
    if isinstance(out.get("items"), dict):
        out["items"] = to_strict(out["items"])
    if isinstance(out.get("$def"), dict):
        out["$def"] = {key: to_strict(value) if isinstance(value, dict) else value
                       for key, value in out["$def"].items()}
    if _is_object(schema):
        required_orig = set(schema.get("required") or [])
        raw_properties = schema.get("properties") or {}
        properties = raw_properties if isinstance(raw_properties, dict) else {}
        new_properties: Dict[str, Any] = {}
        for key, sub in properties.items():
            if not isinstance(sub, dict):
                new_properties[key] = sub
                continue
            transformed = to_strict(sub)
            if key not in required_orig:
                transformed = make_nullable(transformed)
            new_properties[key] = transformed
        out["properties"] = new_properties
        out["required"] = list(new_properties.keys())
        out["additionalProperties"] = False
    return out


def _type_matches(expected: str, value: Any) -> bool:
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True  # 未知类型不阻断（与 tool_schema._matches_type 同口径）


def _branch_matches(branch: Dict[str, Any], value: Any) -> bool:
    if "const" in branch:
        const = branch["const"]
        if isinstance(const, bool) != isinstance(value, bool):
            return False
        if const != value:
            return False
    expected = branch.get("type")
    if expected is not None:
        options = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(option, value) for option in options):
            return False
    if _is_object(branch) and isinstance(value, dict):
        if not all(key in value for key in (branch.get("required") or [])):
            return False
    return True


def matching_any_of_branch(branches: Sequence[Dict[str, Any]], value: Any
                           ) -> Optional[Dict[str, Any]]:
    """返回第一个结构上匹配 ``value`` 的 ``anyOf`` 分支；都不匹配返回 ``None``。"""
    for branch in branches:
        if _branch_matches(branch, value):
            return branch
    return None


def strip_nulls(args: Any, original_schema: Dict[str, Any]) -> Any:
    """删掉 strict 输出里"原 schema 可选、值为 null"的键；原地修改并返回。

    递归进 object、array items 与匹配上的 anyOf 分支；**原 schema 必填键的 null
    保留**（删了会变成"缺必填字段"的另一种非法）。非 dict 的 schema 段（如空
    schema ``{}``）没有 properties 可剥，原样返回。
    """
    if args is None:
        return args
    if isinstance(args, list):
        items = original_schema.get("items")
        if isinstance(items, dict):
            for item in args:
                strip_nulls(item, items)
        return args
    if not isinstance(args, dict):
        return args

    schema = original_schema
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        matched = matching_any_of_branch(any_of, args)
        if matched is not None:
            schema = matched
    required = set(schema.get("required") or [])
    raw_properties = schema.get("properties") or {}
    properties = raw_properties if isinstance(raw_properties, dict) else {}
    for key in list(args.keys()):
        value = args[key]
        if value is None and key not in required:
            del args[key]
            continue
        prop_schema = properties.get(key)
        if isinstance(prop_schema, dict):
            strip_nulls(value, prop_schema)
    return args
