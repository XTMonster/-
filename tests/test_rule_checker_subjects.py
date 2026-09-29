"""v1.4 X9 / RK-19：被摄主体与银幕方向连续性的判定口径。

* X9：``SceneContext.subjects_for`` **不再回退整个剧组**——镜头没显式声明
  角色就该有"没有主体"的结论，否则空镜/无声明镜头会混进 R012 的正反打判定。
* RK-19：只有**相邻两镜都显式声明**的同一角色才参与银幕方向翻转判定；
  只在一镜里声明的角色不参与。判定逻辑抽在无 bpy 的 ``cinema/axis.py``。
"""

from __future__ import annotations

from block_director.contracts.cast import CastMember, SceneSpec
from block_director.contracts.plan import Plan
from block_director.cinema.axis import (
    flipped_screen_directions,
    shared_characters,
)
from block_director.cinema.subjects import resolve_subjects, subject_ids


def _shot(declared: list):
    plan = Plan.from_dict({"shots": [
        {"shot_id": "shot_001", "order": 1, "intent": "x", "shot_type": "MS",
         "duration_frames": 48, "characters": declared}]})
    return plan.shots[0]


def _cast():
    return [CastMember(id="char_001", name="米迦尔"),
            CastMember(id="char_002", name="伊恩")]


def test_declared_subjects_are_returned():
    shot = _shot(["char_001"])
    assert subject_ids(shot, has_plan=True) == ["char_001"]
    assert [item.id for item in resolve_subjects(shot, _cast(),
                                                 has_plan=True)] == ["char_001"]


def test_a_shot_without_declarations_has_no_subjects():
    shot = _shot([])
    assert subject_ids(shot, has_plan=True) == []
    assert resolve_subjects(shot, _cast(), has_plan=True) == []


def test_without_any_plan_the_whole_cast_still_falls_back():
    """计划外的临时调用（没有 plan）保留历史行为。"""
    assert subject_ids(None, has_plan=False) is None
    assert len(resolve_subjects(None, _cast(), has_plan=False)) == 2
    assert subject_ids(None, has_plan=True) == []


# --------------------------------------------------------------------------- #
# RK-19：银幕方向翻转
# --------------------------------------------------------------------------- #
def test_shared_characters_requires_both_shots_to_declare():
    assert shared_characters(["a", "b"], ["b", "c"]) == ["b"]
    assert shared_characters(["a"], ["b"]) == []


def test_flip_is_reported_when_signs_differ():
    flipped = flipped_screen_directions(
        {"a": +0.8}, {"a": -0.6}, ["a"])
    assert flipped == ["a"]


def test_same_sign_is_not_a_flip():
    assert flipped_screen_directions({"a": +0.8}, {"a": +0.6}, ["a"]) == []


def test_neutral_reading_is_not_a_flip():
    """中性（骑轴）不算翻转——否则每个中性机位都会被误报。"""
    assert flipped_screen_directions({"a": +0.8}, {"a": 0.0}, ["a"]) == []
    assert flipped_screen_directions({"a": 1e-6}, {"a": -0.6}, ["a"]) == []


def test_only_characters_declared_in_both_shots_participate():
    """负例：只在一镜里声明的角色不参与判定（R019 的门就是"两镜都声明"）。"""
    previous = {"a": +0.8, "b": +0.5}
    current = {"b": -0.5}
    # 两镜都声明：b 参与，且真的翻转。
    assert shared_characters(["a", "b"], ["b"]) == ["b"]
    assert flipped_screen_directions(previous, current, ["b"]) == ["b"]
    # 只有前一镜声明 a（当前镜没有 a 的读数）→ 不参与、不报。
    assert flipped_screen_directions(previous, {"c": -0.5},
                                     ["a"]) == []
