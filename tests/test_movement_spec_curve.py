"""v1.6 D2（FR-B4）接线：计划里运镜声明的 ``curve`` 必须一路传到写关键帧那一层。

纯层 ``movement_spec`` 规整这个词（缺省 smooth、闭集外报错），引擎侧
``shot_builder.apply_declared_movements`` 把它交给 ``apply_camera_movement``。
后者的接线在 bpy 里，这里用 AST 钉住"调用时真的传了 curve"。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from block_director.cinema.camera_motion import movement_curve, movement_spec
from block_director.contracts.rhythm import CURVE_VALUES, DEFAULT_CURVE

ROOT = Path(__file__).resolve().parents[1]


def test_curve_defaults_to_smooth_when_absent():
    assert movement_curve({"type": "dolly_in"}) == DEFAULT_CURVE == "smooth"
    assert movement_curve("dolly_in") == "smooth"


@pytest.mark.parametrize("curve", CURVE_VALUES)
def test_every_closed_set_curve_is_carried(curve):
    assert movement_curve({"type": "dolly_in", "curve": curve}) == curve


def test_out_of_set_curve_is_rejected_not_replaced():
    with pytest.raises(ValueError) as info:
        movement_curve({"type": "dolly_in", "curve": "bounce"})
    assert "bounce" in str(info.value)


def test_movement_spec_shape_is_unchanged_by_the_curve_field():
    """curve 走独立函数：``movement_spec`` 的返回形状一个键都不多。"""
    spec = movement_spec({"type": "dolly_in", "curve": "sharp"},
                         shot_start=1, shot_end=48)
    assert "curve" not in spec


def test_shot_builder_passes_the_curve_to_the_engine():
    tree = ast.parse((ROOT / "block_director" / "layer3_engine" / "shot_builder.py")
                     .read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and getattr(node.func, "id", "") == "apply_camera_movement"]
    assert calls, "shot_builder 不再调用 apply_camera_movement？"
    for call in calls:
        keywords = {kw.arg for kw in call.keywords}
        assert "curve" in keywords, "运镜声明的 curve 没有交给引擎：生产路径恒为 smooth"
