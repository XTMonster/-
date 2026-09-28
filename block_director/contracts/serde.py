"""数据类 ↔ 纯 JSON 类型的通用转换（执行文档 v1.2 §16.5 单一真源）。

配置（§21.5）与 SDL（§5.1）都要落盘成 JSON，若各写一套转换器，很快就会出现
"这个字段存了、那个没存"的漂移。这里提供唯一的一套：

- 枚举（StrEnum 子类）→ 字符串值；
- 嵌套 dataclass → 递归字典；
- list/tuple/dict 递归；
- 反向按类型注解还原，支持 ``Optional`` / ``Union``。
"""

from __future__ import annotations

import typing
from dataclasses import fields, is_dataclass
from typing import Any, Dict, List, Tuple


def to_plain(value: Any) -> Any:
    """把任意 dataclass/枚举结构转成可 JSON 序列化的纯类型。"""
    if isinstance(value, str):        # StrEnum 也是 str，且 __str__ 已返回 value
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain(item) for item in value]
    return value


def _is_enum_type(annotation: Any) -> bool:
    return (isinstance(annotation, type) and issubclass(annotation, str)
            and hasattr(annotation, "__members__"))


def coerce(annotation: Any, value: Any) -> Any:
    """按类型注解还原标量/枚举/嵌套 dataclass。"""
    origin = typing.get_origin(annotation)
    if origin in (list, List):
        args = typing.get_args(annotation)
        item_type = args[0] if args else Any
        return [coerce(item_type, item) for item in (value or [])]
    if origin in (tuple, Tuple):
        # 固定长度元组按位置还原，变长元组（Tuple[float, ...]）按元素还原；
        # 必须回到 tuple，否则 ``to_plain`` → ``from_plain`` 会把类型悄悄改掉。
        args = typing.get_args(annotation)
        items = list(value or [])
        if len(args) == len(items) and len(set(args)) > 1:
            return tuple(coerce(arg, item) for arg, item in zip(args, items))
        item_type = args[0] if args else Any
        return tuple(coerce(item_type, item) for item in items)
    if origin in (dict, Dict):
        args = typing.get_args(annotation)
        value_type = args[1] if len(args) > 1 else Any
        return {str(key): coerce(value_type, item)
                for key, item in (value or {}).items()}
    if origin is typing.Union:                       # 含 Optional[X]
        if value is None:
            return None
        for option in typing.get_args(annotation):
            if option is type(None):
                continue
            return coerce(option, value)
        return value
    if is_dataclass(annotation) and isinstance(value, dict):
        return from_plain(annotation, value)
    if _is_enum_type(annotation):
        return annotation(value)
    if annotation is bool:
        return bool(value)
    if annotation is int:
        return int(value)
    if annotation is float:
        return float(value)
    if annotation is str:
        return str(value)
    return value


def from_plain(cls: Any, data: Dict[str, Any]) -> Any:
    """按数据类的字段与注解，从字典还原实例（缺字段用默认值）。"""
    hints = typing.get_type_hints(cls)
    kwargs: Dict[str, Any] = {}
    for field_info in fields(cls):
        if field_info.name not in data:
            continue
        kwargs[field_info.name] = coerce(hints.get(field_info.name, Any),
                                         data[field_info.name])
    return cls(**kwargs)
