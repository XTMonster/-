"""同层时间轴占用表（v1.6 卡 F4 / D-16）。

钉住五条：同层重叠区间**原样**列出、不同层互不干扰、输出确定、
空输入 → 空表、渲染文本含整数帧区间；再补拍点编译复用、多轨展开、
``fps`` 秒键折算、角色过滤与"不静默吞错"几条。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from block_director.layer5_orchestrator.beat_compiler import (  # noqa: E402
    BEAT_DURATION_TABLE,
    WALK_METRES_PER_FRAME,
)
from block_director.layer5_orchestrator.occupancy import (  # noqa: E402
    layer_occupancy,
    render_occupancy_table,
)


def _action(character_id, action_type, start, end, **params):
    payload = {"character_id": character_id, "action_type": action_type,
               "start_frame": start, "end_frame": end}
    if params:
        payload["params"] = params
    return payload


def _beat(t, subject, verb, **kwargs):
    payload = {"t": t, "subject": subject, "verb": verb}
    payload.update(kwargs)
    return payload


# --------------------------------------------------------------------------- #
# 帧级动作：同层重叠原样列出 / 不同层互不干扰
# --------------------------------------------------------------------------- #
def test_same_layer_overlapping_intervals_are_listed_verbatim():
    """计划里两条同层重叠的动作都在表里，帧区间不合并、不后移。"""
    occupancy = layer_occupancy([
        _action("char_001", "turn_body", 10, 20),
        _action("char_002", "turn_body", 15, 30),
    ])
    assert occupancy["base"] == [
        (10, 20, "char_001:turn_body"),
        (15, 30, "char_002:turn_body"),
    ]


def test_different_layers_do_not_interfere():
    """同帧窗但不同层的动作各归各层，谁也不被推开。"""
    occupancy = layer_occupancy([
        _action("char_001", "turn_body", 10, 20),
        _action("char_001", "turn_head", 10, 20),
    ])
    assert occupancy["base"] == [(10, 20, "char_001:turn_body")]
    assert occupancy["head"] == [(10, 20, "char_001:turn_head")]


def test_multi_layer_actions_expand_to_every_layer_they_touch():
    """层归属单一真源 = ``motion/model.py::expand``：多轨动作一层不漏。"""
    walk = layer_occupancy([_action("char_001", "walk_to", 1, 40)])
    assert sorted(walk) == ["base", "legs"]
    sit = layer_occupancy([_action("char_001", "sit", 1, 24)])
    assert sorted(sit) == ["base", "body", "legs"]
    run = layer_occupancy([_action("char_001", "run_to", 1, 30)])
    assert sorted(run) == ["base", "body", "legs"]
    nod = layer_occupancy([_action("char_001", "nod", 5, 16)])
    assert sorted(nod) == ["head"]


def test_output_is_deterministic_and_layers_follow_all_layers_order():
    items = [
        _action("char_002", "turn_head", 30, 41),
        _action("char_001", "sit", 10, 33),
        _action("char_001", "walk_to", 40, 60),
    ]
    first = layer_occupancy(items)
    second = layer_occupancy(list(reversed(items)))
    assert first == second
    assert list(first) == ["base", "body", "head", "legs"]
    for layer, intervals in first.items():
        assert intervals == sorted(intervals,
                                   key=lambda entry: (entry[0], entry[1],
                                                      entry[2]))
        for start, end, owner in intervals:
            assert isinstance(start, int) and isinstance(end, int)
            assert isinstance(owner, str)


def test_non_action_non_beat_items_are_skipped_like_beat_compiler():
    occupancy = layer_occupancy([
        {"dialogue": "这不是动作"},
        _action("char_001", "nod", 5, 16),
    ])
    assert occupancy == {"head": [(5, 16, "char_001:nod")]}


# --------------------------------------------------------------------------- #
# 拍点 → 编译复用（不重写估时）
# --------------------------------------------------------------------------- #
def test_beats_are_compiled_by_beat_compiler():
    occupancy = layer_occupancy(
        [_beat(0.5, "char_001", "nod"), _beat(0.0, "char_002", "turn_body")],
        duration_frames=100)
    assert occupancy["head"] == [(50, 50 + BEAT_DURATION_TABLE["nod"] - 1,
                                  "char_001:nod")]
    assert occupancy["base"] == [
        (1, BEAT_DURATION_TABLE["turn_body"], "char_002:turn_body")]


def test_beats_take_the_serialised_timeline_not_the_raw_one():
    """拍点按构建期真落的时间轴列：重叠的后者被编译器后移后才进表。"""
    occupancy = layer_occupancy(
        [_beat(0.0, "char_001", "turn_body"),
         _beat(0.1, "char_001", "turn_body")],
        duration_frames=100)
    first_end = BEAT_DURATION_TABLE["turn_body"]
    assert occupancy["base"] == [
        (1, first_end, "char_001:turn_body"),
        (first_end + 1, first_end + BEAT_DURATION_TABLE["turn_body"],
         "char_001:turn_body"),
    ]


def test_beats_walk_resolution_flows_through_anchors_and_cast():
    occupancy = layer_occupancy(
        [_beat(0.0, "char_001", "walk_to", target="door")],
        duration_frames=200,
        anchors={"door": [4.0, 0.0, 0.0]},
        cast={"char_001": [0.0, 0.0, 0.0]})
    frames = round(4.0 / WALK_METRES_PER_FRAME)
    assert sorted(occupancy) == ["base", "legs"]
    assert occupancy["base"] == [(1, frames, "char_001:walk_to")]
    assert occupancy["legs"] == [(1, frames, "char_001:walk_to")]


def test_beats_without_duration_frames_raise_instead_of_guessing():
    with pytest.raises(ValueError, match="duration_frames"):
        layer_occupancy([_beat(0.5, "char_001", "nod")])


# --------------------------------------------------------------------------- #
# 载体 / 混合输入 / 秒键
# --------------------------------------------------------------------------- #
def test_shot_like_carrier_combines_actions_and_beats():
    shot = {
        "shot_id": "shot_001",
        "duration_frames": 100,
        "actions": [_action("char_001", "turn_body", 1, 18)],
        "beats": [_beat(0.5, "char_002", "nod")],
        "dialogues": [],
    }
    occupancy = layer_occupancy(shot)
    assert occupancy["base"] == [(1, 18, "char_001:turn_body")]
    assert occupancy["head"] == [
        (50, 50 + BEAT_DURATION_TABLE["nod"] - 1, "char_002:nod")]


def test_seconds_based_action_keys_are_scaled_by_fps():
    action = {"character_id": "char_001", "action_type": "nod",
              "start_s": 0.5, "end_s": 1.0}
    at_24 = layer_occupancy([dict(action)], fps=24)
    at_30 = layer_occupancy([dict(action)], fps=30)
    assert at_24["head"] == [(12, 24, "char_001:nod")]
    assert at_30["head"] == [(15, 30, "char_001:nod")]


def test_unknown_action_type_raises_instead_of_being_silently_dropped():
    with pytest.raises(ValueError, match="未知动作类型"):
        layer_occupancy([_action("char_001", "bogus", 1, 5)])


def test_malformed_frame_value_raises_instead_of_defaulting():
    with pytest.raises(ValueError, match="start_frame"):
        layer_occupancy([{"character_id": "char_001", "action_type": "nod",
                          "start_frame": "abc", "end_frame": 10}])


# --------------------------------------------------------------------------- #
# 空输入 / 渲染
# --------------------------------------------------------------------------- #
def test_empty_inputs_produce_empty_table():
    assert layer_occupancy(None) == {}
    assert layer_occupancy([]) == {}
    assert layer_occupancy({}) == {}
    assert render_occupancy_table({}) == ""


def test_rendered_text_has_one_line_per_interval_with_integer_ranges():
    occupancy = layer_occupancy([
        _action("char_001", "turn_body", 12, 30),
        _action("char_001", "turn_head", 20, 31),
    ])
    text = render_occupancy_table(occupancy)
    lines = text.splitlines()
    assert len(lines) == 2
    assert "base: 12-30 char_001:turn_body" in lines
    assert "head: 20-31 char_001:turn_head" in lines
    assert "12-30" in text and "20-31" in text


def test_character_id_filter_keeps_only_that_characters_lines():
    occupancy = layer_occupancy([
        _action("char_001", "turn_body", 1, 10),
        _action("char_002", "nod", 5, 16),
    ])
    text = render_occupancy_table(occupancy, character_id="char_001")
    assert "char_001:turn_body" in text
    assert "char_002" not in text
    assert len(text.splitlines()) == 1
    assert render_occupancy_table(occupancy, character_id="char_999") == ""
