"""目标模型规格表 loader（v1.7 卡 A5 / TDD §12.1，R-痛点 M2 契约半）。

数据本体在 ``specs/target_models.yaml``（不许硬编码进 py）。本模块只负责
读取与**区间键**的形态校验；其余键（分辨率、fps 等标量）不校验形态，
``raw`` 原样保留——各模型字段不同构，不强归一。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .config import parse_yaml

#: 区间合法性**只校验这三个键名**（卡 A5 钉死，不外推）：
#: 值必须是 len==2 且 lo<hi 的数值列表，违反即抛错（不静默）。
RANGE_KEYS = ("aspect_range", "ref_recommend_s", "segment_range_s")


class TargetModelError(ValueError):
    """目标模型规格表不可读/形态非法（结构化错误，不静默回落）。"""


@dataclass
class ModelSpec:
    label: str
    #: 原始键全保留（各模型字段不同构，不强归一）
    raw: Dict[str, Any]


def default_table_path() -> Path:
    return Path(__file__).resolve().parents[2] / "specs" / "target_models.yaml"


def _check_range_keys(key: str, value: Any, model: str) -> None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise TargetModelError(
            f"{model}.{key} 必须是两元素列表（当前 {value!r}）")
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise TargetModelError(
            f"{model}.{key} 必须由数值组成（当前 {value!r}）") from exc
    if not low < high:
        raise TargetModelError(
            f"{model}.{key} 必须满足 lo < hi（当前 {value!r}）")


def load_table(path: Optional[Path] = None) -> Dict[str, ModelSpec]:
    """读取 ``specs/target_models.yaml``。

    缺文件 / 根非映射 / 缺 ``label`` / 区间键非法 → :class:`TargetModelError`
    （**抛错不静默**，TDD §12.1 钉死）。
    """
    target = Path(path) if path is not None else default_table_path()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise TargetModelError(f"目标模型规格表不可读：{target}") from exc
    raw = parse_yaml(text)
    if not isinstance(raw, dict):
        raise TargetModelError("目标模型规格表根节点必须是映射")
    table: Dict[str, ModelSpec] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            raise TargetModelError(f"模型 {name!r} 必须是映射")
        label = entry.get("label")
        if not isinstance(label, str) or not label:
            raise TargetModelError(f"模型 {name!r} 缺少非空 label")
        for key in RANGE_KEYS:
            if key in entry:
                _check_range_keys(key, entry[key], str(name))
        table[str(name)] = ModelSpec(label=label, raw=dict(entry))
    return table
