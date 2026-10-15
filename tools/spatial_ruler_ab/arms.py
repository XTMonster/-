"""两臂提示渲染（spec §15.2/15.4）。

本模块只做一件事：把"同一场景"渲染成基线臂（无测量）与尺子臂（含测量读数）
两种提示，并保证尺子臂不含处方答案。fixtures 里的 _measurement_block 是渲染
真身；这里提供公共入口与 demo schema 常驻引用，供评分器对拍。

DEMO_ACTION_TOOL_SCHEMAS 是评测台（AB 台）的本地夹具，真源在
``layer3_engine/tool_bindings`` 的注册表；本模块从 ``schemas.py`` 导入它，
不再依赖 prescription.py 的旧同名常量（03a 已删除）。
"""
from __future__ import annotations

from .fixtures import _measurement_block
from .schemas import DEMO_ACTION_TOOL_SCHEMAS


def render_measurement_block(scene) -> str:
    """公共入口：给定构图场景 dict，返回尺子读数块。"""
    return _measurement_block(scene)
