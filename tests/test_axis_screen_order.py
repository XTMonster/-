"""v1.6 B5（FR-C6 / D-14）：银幕左右序状态机的纯层测试。

接口（TDD §4.3，钉死）：

* ``ScreenOrderState(left_to_right, facing_sign)`` —— 一镜画面左→右的角色序
  ＋ 每个角色的朝向符号（-1 / 0 / +1）；
* ``update_order(state, samples)`` —— 把一帧的 ``ScreenSample`` 折进状态机；
* ``axis_violation(prev, cur, bridge_ok)`` —— 左右序翻转且无合法桥接时返回
  ``GuardWarning(type="axis_screen_order", severity=ERROR)``，否则 ``None``。

朝向符号 = 头部朝向向量投影到画面 X 轴的符号；``|投影| < 0.1`` 记 0（中性）。
``bridge_ok`` = 中间隔了中性镜（双方 facing_sign≈0）或骑轴镜 ⇒ 合法换侧。
"""

from __future__ import annotations

import json
import math

from block_director.cinema.axis import (
    Axis,
    FACING_SIGN_EPS,
    ScreenOrderState,
    ScreenSample,
    axis_violation,
    facing_sign_of,
    update_order,
)
from block_director.contracts.guard import Confidence, Severity


def _sample(character_id: str, screen_x: float, facing_x: float) -> ScreenSample:
    return ScreenSample(character_id=character_id,
                        screen_x=float(screen_x), facing_x=float(facing_x))


def _state(order, facing=None) -> ScreenOrderState:
    return ScreenOrderState(left_to_right=tuple(order),
                            facing_sign=dict(facing or {}))


# --------------------------------------------------------------------------- #
# update_order：排序、朝向符号、阈值边界、确定性
# --------------------------------------------------------------------------- #
def test_update_order_sorts_by_screen_x_and_signs_facing():
    state = update_order(
        _state(("甲", "乙")),
        [_sample("乙", 0.2, +0.9), _sample("甲", 0.8, -0.6)])
    assert state.left_to_right == ("乙", "甲")
    assert state.facing_sign == {"乙": 1, "甲": -1}


def test_facing_sign_is_neutral_inside_the_threshold():
    """|投影| < 0.1 ⇒ 0；正好 0.1 仍取符号（阈值是严格小于）。"""
    assert facing_sign_of(0.0) == 0
    assert facing_sign_of(+0.05) == 0
    assert facing_sign_of(-0.05) == 0
    below = math.nextafter(FACING_SIGN_EPS, 0.0)   # 最大的 < 0.1 的浮点数
    assert facing_sign_of(below) == 0
    assert facing_sign_of(-below) == 0
    #: 边界本身不是中性
    assert facing_sign_of(FACING_SIGN_EPS) == 1
    assert facing_sign_of(-FACING_SIGN_EPS) == -1


def test_update_order_applies_the_same_threshold():
    state = update_order(
        _state(()),
        [_sample("甲", 0.2, 0.1), _sample("乙", 0.8, -0.1)])
    assert state.facing_sign == {"甲": 1, "乙": -1}
    neutral = update_order(
        _state(()),
        [_sample("甲", 0.2, math.nextafter(0.1, 0.0)),
         _sample("乙", 0.8, -math.nextafter(0.1, 0.0))])
    assert neutral.facing_sign == {"甲": 0, "乙": 0}


def test_update_order_is_deterministic_and_tie_broken_by_previous_order():
    shuffled = [_sample("乙", 0.5, +0.9), _sample("甲", 0.5, -0.9)]
    first = update_order(_state(("甲", "乙")), shuffled)
    second = update_order(_state(("甲", "乙")), list(reversed(shuffled)))
    third = update_order(_state(("甲", "乙")), shuffled)
    assert first == second == third
    #: 屏幕 X 相同 ⇒ 先按上一状态的顺序决序（确定性），不随样本输入顺序漂移。
    assert first.left_to_right == ("甲", "乙")


def test_update_order_keeps_unobserved_characters_and_empty_is_identity():
    state = update_order(_state(("甲", "乙"), {"甲": 1, "乙": -1}),
                         [_sample("甲", 0.8, +0.6)])
    assert state.left_to_right == ("甲", "乙")
    assert state.facing_sign == {"甲": 1, "乙": -1}
    base = _state(("甲", "乙"), {"甲": 1, "乙": -1})
    assert update_order(base, []) is base


def test_update_order_rejects_non_sample_input_loudly():
    import pytest

    with pytest.raises(TypeError):
        update_order(_state(()), [{"character_id": "甲"}])


# --------------------------------------------------------------------------- #
# axis_violation：正反打保持 / 直接换侧 / 中性桥接
# --------------------------------------------------------------------------- #
def test_reverse_shot_pair_keeping_order_has_no_violation():
    """正反打：左右序不变（朝向符号互翻是正反打的本体），不告警。"""
    previous = _state(("甲", "乙"), {"甲": -1, "乙": +1})
    current = _state(("甲", "乙"), {"甲": +1, "乙": -1})
    assert axis_violation(previous, current, bridge_ok=False) is None


def test_a_direct_swap_is_an_error_with_both_orders_in_evidence():
    previous = _state(("甲", "乙"), {"甲": -1, "乙": +1})
    current = _state(("乙", "甲"), {"甲": +1, "乙": -1})
    warning = axis_violation(previous, current, bridge_ok=False)
    assert warning is not None
    assert warning.type == "axis_screen_order"
    assert warning.severity is Severity.ERROR
    assert warning.confidence is Confidence.HIGH
    assert warning.evidence["previous_order"] == ["甲", "乙"]
    assert warning.evidence["current_order"] == ["乙", "甲"]
    assert warning.problems() == ""
    assert json.dumps(warning.to_dict())  # 证据必须可 JSON 序列化


def test_a_swap_bridged_by_a_neutral_shot_is_allowed():
    previous = _state(("甲", "乙"), {"甲": -1, "乙": +1})
    current = _state(("乙", "甲"), {"甲": -1, "乙": +1})
    assert axis_violation(previous, current, bridge_ok=True) is None
    #: 中性镜的定义：双方 facing_sign 全 0（正/背对相机）——由阈值折出来。
    bridge = update_order(
        _state(()),
        [_sample("甲", 0.5, 0.05), _sample("乙", 0.5, -0.05)])
    assert bridge.facing_sign == {"甲": 0, "乙": 0}


def test_same_order_needs_no_bridge():
    previous = _state(("甲", "乙"))
    current = _state(("甲", "乙"))
    assert axis_violation(previous, current, bridge_ok=False) is None


def test_a_swap_between_different_character_sets_is_not_judged():
    """只有同一对角色都出现时才比较左右序（与老口径"两镜 id 集相等"一致）。"""
    previous = _state(("甲", "乙"))
    current = _state(("乙", "丙"))
    assert axis_violation(previous, current, bridge_ok=False) is None


def test_an_empty_state_is_never_a_violation():
    assert axis_violation(ScreenOrderState(), ScreenOrderState(),
                          bridge_ok=False) is None
    assert axis_violation(_state(("甲", "乙")), ScreenOrderState(),
                          bridge_ok=False) is None


# --------------------------------------------------------------------------- #
# 旧入口回归：axis_controller.py / tests/test_axis.py 仍按 (Axis, camera) 调用
# --------------------------------------------------------------------------- #
def test_the_legacy_axis_camera_entrypoint_still_returns_text():
    axis = Axis(start=(-1.0, 0.0), end=(1.0, 0.0),
                established_side=1, left_label="小明", right_label="小红")
    assert axis_violation(axis, (1.0, 4.0)) is None
    message = axis_violation(axis, (1.0, -4.0))
    assert isinstance(message, str) and "180° 轴线" in message
