"""v1.4 US-17 / D-5：同层动作重叠必须**自动错开**并留痕。

v1.3 的 ``check_conflicts`` 只会**拒绝**（``ValueError("动作冲突…")``），于是
"模型把两个动作挤在同一段帧里"会让整条镜头直接失败。v1.4 要求：

* 同层重叠 → **错开**（后一个动作整体后移，留出交叉淡化窗口）；
* 语义禁忌对（§9.7）→ **不**自动错开，照旧报错（"边走边倒地"改时间也荒谬）；
* 每次错开都留一条痕，供 ``shots.json.action_conflicts[]`` 对拍。

判据是**外生**的：错开之后重新扫一遍关键帧区间，重叠帧数必须为 0；不取
``stagger_conflicts`` 自己的返回值当结论。
"""

from __future__ import annotations

from block_director.motion.model import (
    BLEND_FRAMES,
    ActionRequest,
    check_conflicts,
    expand,
    stagger_conflicts,
)


def _walk(start: int, end: int) -> ActionRequest:
    return ActionRequest("walk_to", start, end,
                         {"target_position": [2.0, 0.0, 0.0]})


def _overlap_frames(requests) -> int:
    """独立重算：同层动作两两之间的重叠帧数之和。"""
    by_layer: dict = {}
    for item in requests:
        for spec in expand(item):
            by_layer.setdefault(spec.layer, []).append(item)
    total = 0
    for entries in by_layer.values():
        unique = {id(item): item for item in entries}.values()
        ordered = sorted(unique, key=lambda item: item.start_frame)
        for previous, current in zip(ordered, ordered[1:]):
            if current.start_frame < previous.end_frame:
                total += previous.end_frame - current.start_frame
    return total


def test_conflicting_same_layer_actions_are_single_track():
    """基线：重叠确实存在，而且会被 check_conflicts 抓到。"""
    requests = [_walk(1, 48), ActionRequest("turn_body", 20, 60)]
    assert _overlap_frames(requests) > 0
    assert check_conflicts(requests)


def test_stagger_removes_every_overlap_and_records_one_event():
    requests = [_walk(1, 48), ActionRequest("turn_body", 20, 60)]
    adjusted, events = stagger_conflicts(requests)

    assert _overlap_frames(adjusted) == 0            # 独立重算，不看返回值
    assert len(events) == 1
    event = events[0]
    assert event["overlap_frames"] > 0
    assert event["applied_shift"] >= event["overlap_frames"]
    assert event["pair"] == ["walk_to", "turn_body"]
    # 错开之后 §9.7 的同层判据必须放行。
    assert [item for item in check_conflicts(adjusted)
            if "层动作时间重叠" in item] == []


def test_stagger_keeps_a_gap_for_the_blend_window():
    adjusted, _events = stagger_conflicts(
        [_walk(1, 48), ActionRequest("turn_body", 40, 80)])
    ordered = sorted(adjusted, key=lambda item: item.start_frame)
    assert ordered[1].start_frame >= ordered[0].end_frame + BLEND_FRAMES


def test_forbidden_pairs_are_not_staggered_away():
    """负例：语义禁忌（边走边摔）不许靠挪时间"修好"。"""
    requests = [_walk(1, 48), ActionRequest("fall_down", 20, 60)]
    adjusted, events = stagger_conflicts(requests)
    assert events == []
    assert check_conflicts(adjusted), "语义禁忌必须继续报错"


def test_unrelated_actions_are_left_alone():
    requests = [_walk(1, 48), ActionRequest("look_at", 1, 48)]
    adjusted, events = stagger_conflicts(requests)
    assert events == []
    assert [(item.action_type, item.start_frame, item.end_frame)
            for item in adjusted] == [
        (item.action_type, item.start_frame, item.end_frame)
        for item in requests]


def test_stagger_is_deterministic():
    first = stagger_conflicts([_walk(1, 48), ActionRequest("turn_body", 20, 60)])
    second = stagger_conflicts([_walk(1, 48), ActionRequest("turn_body", 20, 60)])
    assert [(a.action_type, a.start_frame, a.end_frame) for a in first[0]] == \
           [(b.action_type, b.start_frame, b.end_frame) for b in second[0]]
    assert first[1] == second[1]
