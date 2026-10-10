"""``*_invalid`` 审计事件的分类器（纯 Python，不 import bpy）。

G2 判据 #8：``draft_invalid`` / ``react_invalid`` / ``repair_invalid`` 每条事件
都要带 ``reason``（与 message 同文）与 ``category``。分类规则按优先级自上而下，
**先命中者胜**（全部是朴素子串匹配，不用正则；顺序刻意：gate 里的 R001 字样
不能先被 cast/enum 吃掉，闭集违规也不能被后面的 param_key/shape 抢走）：

1. ``no_tool``   —— 没有工具调用；
2. ``gate``      —— R001 / 连线 / 跨线 / 工具调用次数超限；
3. ``cast``      —— 角色表外 / 不在本镜角色 / 既不在角色表 / 找不到角色；
4. ``enum``      —— 闭集 / 取值必须是 / toward 取值 / 只能是；
5. ``param_key`` —— 不认识的参数 / 不允许出现字段；
6. ``shape``     —— 必须是坐标 / 至少需要 / 最多 / 类型应为 / 缺少必填 /
                    必须是数字 / 缺少 rule / 缺少 subject；
7. ``other``     —— 以上都不命中。

取值完全来自 v10–v13 真跑日志里的逐字行（``work/_g2_ds_run/blender_v1{0,1,2,3}.log``），
不是推测；新出现的文案落进 ``other`` 也比猜一个错类别安全。
"""

from __future__ import annotations

from typing import Iterable, Tuple

_RULE_TABLE: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("no_tool", ("没有工具调用",)),
    ("gate", ("R001", "连线", "跨线", "工具调用次数超限")),
    ("cast", ("角色表外", "不在本镜角色", "既不在角色表", "找不到角色")),
    ("enum", ("闭集", "取值必须是", "toward 取值", "只能是")),
    ("param_key", ("不认识的参数", "不允许出现字段")),
    ("shape", ("必须是坐标", "至少需要", "最多", "类型应为", "缺少必填",
               "必须是数字", "缺少 rule", "缺少 subject")),
)


def classify_invalid(reason: str) -> str:
    """按 :data:`_RULE_TABLE` 的顺序给一条 invalid 文案分类；都不命中返回 ``other``。"""
    text = str(reason)
    for category, markers in _RULE_TABLE:
        if any(marker in text for marker in markers):
            return category
    return "other"


__all__: Iterable[str] = ("classify_invalid",)
