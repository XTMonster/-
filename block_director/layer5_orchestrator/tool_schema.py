"""极简 JSON Schema 子集校验器（执行文档 v1.2 §7.5）。

为什么不直接用 jsonschema：那是个第三方依赖，而本模块要在 **Blender 自带
Python**（3.13，无 site-packages）里运行。工具参数校验只用到 JSON Schema
的一小部分，自己实现即可，零依赖、可单测。

支持：type（含联合类型）、required、properties、additionalProperties=false、
items、enum、minimum、maximum、minItems、maxItems。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

_TYPE_MAP = {
    "string": str,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _matches_type(expected: str, value: Any) -> bool:
    if expected == "null":
        return value is None
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    py_type = _TYPE_MAP.get(expected)
    if py_type is str:
        return isinstance(value, str)
    if py_type is bool:
        return isinstance(value, bool)
    if py_type is None:      # 未知类型：不阻断
        return True
    return isinstance(value, py_type)


def _validate(schema: Dict[str, Any], value: Any, path: str,
              problems: List[str]) -> None:
    expected = schema.get("type")
    if expected is not None:
        options: Sequence[str] = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(option, value) for option in options):
            problems.append(f"{path} 类型应为 {'/'.join(options)}，实际 {type(value).__name__}")
            return

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        problems.append(f"{path} 取值必须是 {enum} 之一，实际 {value!r}")

    if isinstance(value, bool):
        return

    if isinstance(value, (int, float)):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            problems.append(f"{path} 不得小于 {minimum}（实际 {value}）")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            problems.append(f"{path} 不得大于 {maximum}（实际 {value}）")

    if isinstance(value, dict):
        for required_key in schema.get("required", []):
            if required_key not in value:
                problems.append(f"{path} 缺少必填字段 {required_key}")
        properties: Dict[str, Any] = schema.get("properties", {})
        for key, sub_value in value.items():
            if key in properties:
                _validate(properties[key], sub_value, f"{path}.{key}", problems)
            elif schema.get("additionalProperties") is False:
                problems.append(f"{path} 不允许出现字段 {key}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            problems.append(f"{path} 至少需要 {min_items} 项（实际 {len(value)}）")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            problems.append(f"{path} 最多 {max_items} 项（实际 {len(value)}）")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _validate(items, item, f"{path}[{index}]", problems)


def validate_args(schema: Dict[str, Any], args: Any) -> List[str]:
    """按 schema 校验参数；返回问题列表，空列表表示通过。"""
    problems: List[str] = []
    _validate(schema, args, "args", problems)
    return problems
