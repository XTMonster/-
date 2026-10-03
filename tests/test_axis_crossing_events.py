"""换位是**看得见的**还是看不见的？——纯计划推算（v1.8）。

为什么（2026-10-04，GLM 5.3 会诊 F2/F4 ＋ `work/_r001_classify_probe.py`）：
R001 的越轴要能说清根因。工艺上"换位"分两种：

* **看得见**：两人同框时有人走过去 ⇒ 合法的轴线重建（观众看得见，方向感没断）；
* **看不见**：在只拍一个人的镜头里绕到另一侧 ⇒ 越轴（观众会觉得两人突然左右互换）。

判据只能在**计划**上推（不读机位）：读了机位就成"构建器自己出题自己判"。
本文件钉 `cinema/axis.crossing_events` 的四件事：看得见/看不见两种换位、单纯走开
不算换位、缺标签不推。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from block_director.cinema.axis import (  # noqa: E402
    Axis,
    axis_state,
    crossing_events,
)
from block_director.contracts.plan import Plan, ShotPlan  # noqa: E402

AXIS = Axis(start=(-0.9, 0.0), end=(0.9, 0.0),
            established_side=-1, left_label="甲", right_label="乙")
INITIAL = {"甲": (-0.9, 0.0, 0.0), "乙": (0.9, 0.0, 0.0)}


def _shot(order: int, characters, walk_target=None) -> ShotPlan:
    payload = {"shot_id": f"shot_{order:03d}", "order": order, "intent": "推进",
               "shot_type": "MS", "duration_frames": 48,
               "characters": list(characters)}
    if walk_target is not None:
        payload["actions"] = [{"character_id": "乙", "action_type": "walk_to",
                               "start_frame": 1, "end_frame": 48,
                               "params": {"target_position": list(walk_target)}}]
    return ShotPlan.from_dict(payload)


def _plan(*shots) -> Plan:
    return Plan(shots=list(shots), scene_heading="INT. 码头 - 日")


#: 乙绕到甲的**另一侧**（连线掉头）
FLIP = (-4.0, 2.0, 0.0)
#: 乙只是走开（连线方向不变）
AWAY = (0.9, -4.0, 0.0)


def test_a_crossing_between_two_people_in_frame_is_marked_visible():
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), FLIP),
                 _shot(3, ("甲", "乙")))
    events = crossing_events(AXIS, plan, INITIAL)
    assert list(events) == ["shot_002"]
    assert events["shot_002"].visible is True
    assert events["shot_002"].people == ("甲", "乙")


def test_a_crossing_hidden_in_a_single_shows_up_as_not_visible():
    """乙在**只拍甲**的那一镜里绕过去——观众看不到，这才是越轴。"""
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲",), FLIP),
                 _shot(3, ("甲", "乙")))
    events = crossing_events(AXIS, plan, INITIAL)
    assert list(events) == ["shot_002"]
    assert events["shot_002"].visible is False


def test_walking_away_rotates_the_line_but_does_not_flip_it():
    """走开会让连线**转**（事件照记，`rotated_deg` 有值），但**不掉头**
    （`flip=False`）——所以它是一次"看得见的重建"而不是"左右换位"。"""
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), AWAY),
                 _shot(3, ("甲", "乙")))
    events = crossing_events(AXIS, plan, INITIAL)
    assert list(events) == ["shot_002"]
    assert events["shot_002"].flip is False
    assert events["shot_002"].rotated_deg > 30.0
    assert events["shot_002"].visible is True


def test_a_plan_without_both_labels_yields_nothing():
    unlabeled = Axis(start=(-0.9, 0.0), end=(0.9, 0.0), established_side=-1)
    plan = _plan(_shot(1, ("甲", "乙")), _shot(2, ("甲", "乙"), FLIP))
    assert crossing_events(unlabeled, plan, INITIAL) == {}


# --------------------------------------------------------------------------- #
# 轴侧状态机：侧别继承，只在**合法桥接**（看得见的换位）处翻转
# --------------------------------------------------------------------------- #
def test_the_side_is_inherited_until_a_visible_crossing_flips_it():
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), FLIP),     # 两人同框：换位看得见 ⇒ 合法
                 _shot(3, ("甲", "乙")),
                 _shot(4, ("甲",)))
    assert axis_state(AXIS, plan, INITIAL) == {
        "shot_001": -1, "shot_002": -1, "shot_003": +1, "shot_004": +1}


def test_an_unseen_crossing_does_not_flip_the_state():
    """看不见的换位**不合法** ⇒ 侧别照旧——于是后续机位仍按原侧，交给规则报违规。"""
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲",), FLIP),          # 只拍甲：换位看不见
                 _shot(3, ("甲", "乙")))
    assert axis_state(AXIS, plan, INITIAL) == {
        "shot_001": -1, "shot_002": -1, "shot_003": -1}


def test_walking_away_never_flips_the_state():
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), AWAY),
                 _shot(3, ("甲", "乙")))
    assert set(axis_state(AXIS, plan, INITIAL).values()) == {-1}
