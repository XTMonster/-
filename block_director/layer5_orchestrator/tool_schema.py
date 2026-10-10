"""极简 JSON Schema 子集校验器（执行文档 v1.2 §7.5）。

为什么不直接用 jsonschema：那是个第三方依赖，而本模块要在 **Blender 自带
Python**（3.13，无 site-packages）里运行。工具参数校验只用到 JSON Schema
的一小部分，自己实现即可，零依赖、可单测。

支持：type（含联合类型）、required、properties、additionalProperties=false、
items、enum、const、anyOf、minimum、maximum、minItems、maxItems。
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


def _const_equal(const: Any, value: Any) -> bool:
    """JSON Schema ``const`` 相等判定：bool 与 int/number 永不相等。

    Python 里 ``True == 1``，但本模块的类型纪律（与 :func:`_matches_type`
    一致）把 boolean 与 integer/number 视为不同 JSON 类型，``const: 1`` 不得
    接受 ``true``。
    """
    if isinstance(const, bool) != isinstance(value, bool):
        return False
    return const == value


def _validate(schema: Dict[str, Any], value: Any, path: str,
              problems: List[str]) -> None:
    if "const" in schema and not _const_equal(schema["const"], value):
        problems.append(f"{path} 取值必须是 {schema['const']!r}，实际 {value!r}")
        return

    expected = schema.get("type")
    if expected is not None:
        options: Sequence[str] = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(option, value) for option in options):
            problems.append(f"{path} 类型应为 {'/'.join(options)}，实际 {type(value).__name__}")
            return

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        problems.append(f"{path} 取值必须是 {enum} 之一，实际 {value!r}")

    any_of: Sequence[Dict[str, Any]] = schema.get("anyOf", ())
    if any_of:
        if not _validate_any_of(any_of, value, path, problems):
            return

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


def _branch_problems(branch: Dict[str, Any], value: Any,
                     path: str) -> List[str]:
    """独立跑一个 ``anyOf`` 分支；返回该分支的问题列表。"""
    problems: List[str] = []
    _validate(branch, value, path, problems)
    return problems


def _validate_any_of(branches: Sequence[Dict[str, Any]], value: Any,
                     path: str, problems: List[str]) -> bool:
    """``anyOf``：任一分支零问题即通过；全部失败按最优分支报告。

    报告顺序（G2 判据 #8）：

    1. 判别式：所有 object 分支都含同一个 ``const`` 键 ``k``，且 ``value``
       是携带 ``k`` 的 dict → 选 ``value[k]`` 命中的分支，只报它的错误，
       路径后缀 ``（k=value[k]）``；
    2. 判别式值未命中任何分支 → ``{path}.{k} 取值必须是 [全部 const] 之一``；
    3. 无判别式 → 选错误最少的那个分支，前缀 ``{path} 不匹配任何允许形状：``。

    返回 True 表示至少一个分支通过；返回 False 时已把最优分支的错误写入
    ``problems``，调用方应直接结束（不再叠加同层其它关键字）。
    """
    results = [_branch_problems(branch, value, path) for branch in branches]
    for branch_problems in results:
        if not branch_problems:
            return True  # 任一分支零问题即整体通过

    object_branches = [branch for branch in branches
                       if branch.get("type") == "object"]
    # 所有 object 分支共有的 const 键；没有 object 分支则无判别式。
    const_keys = None
    for branch in object_branches:
        keys = {key for key, sub in branch.get("properties", {}).items()
                if isinstance(sub, dict) and "const" in sub}
        const_keys = keys if const_keys is None else const_keys & keys
        if not const_keys:
            break
    const_keys = const_keys or set()

    if const_keys and isinstance(value, dict):
        key = sorted(const_keys)[0]
        actual = value.get(key)
        if key in value:
            for branch, branch_problems in zip(branches, results):
                props = branch.get("properties", {})
                key_schema = props.get(key, {}) if isinstance(props, dict) else {}
                const = key_schema.get("const")
                if "const" in key_schema and _const_equal(const, actual):
                    suffix = f"（{key}={actual}）"
                    for problem in branch_problems:
                        problems.append(problem.replace(path, f"{path}{suffix}", 1))
                    return False
            consts = [branch["properties"][key]["const"] for branch in object_branches]
            problems.append(
                f"{path}.{key} 取值必须是 {consts!r} 之一，实际 {actual!r}")
            return False

    best = min(results, key=len)
    problems.append(f"{path} 不匹配任何允许形状")
    problems.extend(best)
    return False


def validate_args(schema: Dict[str, Any], args: Any) -> List[str]:
    """按 schema 校验参数；返回问题列表，空列表表示通过。"""
    problems: List[str] = []
    _validate(schema, args, "args", problems)
    return problems
