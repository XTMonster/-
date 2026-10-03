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
    AXIS_DRIFT_DEG,
    Axis,
    axis_state,
    camera_side_of,
    crossing_events,
    drift_is_bridged,
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


def test_the_exemption_must_be_paid_for_not_merely_mentioned():
    """**赦免额要对得上欠账额**（会诊 F1，2026-10-04，`...-glm-consult-v19b/`）。

    原判据是存在性的："历史上**有过一次**看得见、转过 ≥5° 的事件 ⇒ 全赦免"。
    它同时错在两个方向，这里各钉一条：

    * 一次 **6°** 的可见换位，不能洗白后来 **53°** 的暗重建（观众只见过 6°）；
    * 全程同框、每步 **4°**、累计 **100°** 的可见慢漂移，不该被判越轴。
    """
    assert not drift_is_bridged(53.0, 6.0, neutral=False)      # 放过 → 现在要报
    assert drift_is_bridged(100.0, 100.0, neutral=False)       # 误判 → 现在要放


def test_the_threshold_drift_itself_is_free():
    """阈值内（≤ `AXIS_DRIFT_DEG`）的漂移本来就免费：没超账，不需要谁来偿付。"""
    assert drift_is_bridged(AXIS_DRIFT_DEG, 0.0, neutral=False)
    assert drift_is_bridged(10.0, 0.0, neutral=False)
    #: 刚好超出阈值一点点，就得有等量的可见旋转垫上。
    assert not drift_is_bridged(AXIS_DRIFT_DEG + 5.0, 4.0, neutral=False)
    assert drift_is_bridged(AXIS_DRIFT_DEG + 5.0, 5.0, neutral=False)


def test_a_neutral_camera_bridges_by_itself():
    """§6.2 的中性机位是**逐镜成立**的交代，与漂移量无关。"""
    assert drift_is_bridged(170.0, 0.0, neutral=True)


#: 会诊 ① 给的两个反例（坐标就是本文件那条轴线的世界坐标：甲 (−0.9,0)、乙 (0.9,0)，
#: 绕中点转，机位半径 3.6）。两个都能证伪"用连线转角猜换边"：
#:   ① 转 **100°**、机位方位 150° ⇒ **不换边**（旧判据 ≥90° ⇒ 误报）；
#:   ② 转 **50°**、机位方位 30° ⇒ **换边**（旧判据 <90° ⇒ 漏报）。
SWEEP_100 = (-1.2126, 1.7727, 0.0)
CAMERA_150 = (-3.1177, 1.8, 0.0)
SWEEP_50 = (0.2570, 1.3789, 0.0)
CAMERA_30 = (3.1177, 1.8, 0.0)


def test_camera_side_uses_the_same_convention_as_the_axis():
    """叉积符号的约定必须与 `Axis.side_of` 一致，否则"换边"会整体反号。"""
    axis = Axis(start=(-0.9, 0.0), end=(0.9, 0.0))
    for point in ((0.0, 1.0), (0.0, -1.0), (2.0, 0.0)):
        assert camera_side_of(axis.start, axis.end, point) == axis.side_of(point)


def test_without_cameras_the_plan_phase_approximation_is_unchanged():
    """没有机位时仍是老口径（转角 ≥90°）——构建器摆机位时只有这一份可用。"""
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), SWEEP_100),
                 _shot(3, ("甲", "乙")))
    event = crossing_events(AXIS, plan, INITIAL)["shot_002"]
    assert round(event.rotated_deg) == 100
    assert event.flip is True


def test_one_hundred_degrees_need_not_flip_when_the_camera_is_not_swept():
    """转 100° 但连线**没有扫过机位** ⇒ 观众看到的左右序没变，不该翻侧（会诊 ①）。"""
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), SWEEP_100),
                 _shot(3, ("甲", "乙")))
    event = crossing_events(AXIS, plan, INITIAL,
                            {"shot_002": CAMERA_150})["shot_002"]
    assert round(event.rotated_deg) == 100
    assert event.flip is False


def test_fifty_degrees_does_flip_when_the_line_sweeps_the_camera():
    """只转 50° 但**扫过了机位** ⇒ 左右序真的换了（旧判据漏掉的就是它）。"""
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), SWEEP_50),
                 _shot(3, ("甲", "乙")))
    event = crossing_events(AXIS, plan, INITIAL,
                            {"shot_002": CAMERA_30})["shot_002"]
    assert round(event.rotated_deg) == 50
    assert event.flip is True


def test_the_state_machine_plumbs_the_cameras_through():
    """精确判据必须有**触达路径**（会诊 ① 第 5 步）：不穿参就等于死参数。"""
    plan = _plan(_shot(1, ("甲", "乙")),
                 _shot(2, ("甲", "乙"), SWEEP_50),
                 _shot(3, ("甲", "乙")))
    assert axis_state(AXIS, plan, INITIAL) == {
        "shot_001": -1, "shot_002": -1, "shot_003": -1}     # 近似：50° < 90° 不翻
    assert axis_state(AXIS, plan, INITIAL, {"shot_002": CAMERA_30}) == {
        "shot_001": -1, "shot_002": -1, "shot_003": 1}      # 精确：扫过机位 ⇒ 翻
