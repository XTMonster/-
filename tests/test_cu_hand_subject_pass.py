"""缺陷 A（T5）：局部主体框——"右手特写"按手部评分。

剧本声明 ``framing_target=character/part=hand`` 时，机位对准手部、手部在
画内，构图分必须严格 >80，且建议不再要求"整身入画"（旧口径把整身框当
主锚，特写永远修不过）。纯层测试；Blender 侧实拍见
``tools/blender_tests/test_local_subject_probe.py``。
"""

from __future__ import annotations

import pytest

from block_director.cinema.composition import PASS_SCORE, SubjectBox
from block_director.cinema.composition import evaluate_composition


def _body_box(**overrides) -> SubjectBox:
    """整身框：几乎占满画面（特写里是"该景别窗口内那一段"，仍是最高盒）。"""
    values = dict(name="米迦尔", left=0.02, right=0.98, top=0.98,
                  bottom=0.02, facing=1.0)
    values.update(overrides)
    return SubjectBox(**values)


def _hand_box(**overrides) -> SubjectBox:
    """手部局部框：落左三分线、朝向画面内侧、高度占比 0.65。"""
    values = dict(name="米迦尔:hand", left=0.24, right=0.42, top=0.95,
                  bottom=0.30, facing=1.0, provenance="anchored")
    values.update(overrides)
    return SubjectBox(**values)


def test_hand_subject_as_primary_passes_strictly_above_80():
    """显式 primary=手部框：特写按手评分，严格 >80。"""
    report = evaluate_composition(
        [_body_box(), _hand_box()], primary="米迦尔:hand",
        expected_height=1.0, headroom_applies=False)
    assert report.score > PASS_SCORE, report.to_dict()


def test_without_primary_whole_body_anchor_drags_below_threshold():
    """对抗：没有局部主体语义时，整身框当主锚会让同一机位修不过。"""
    report = evaluate_composition([_body_box(), _hand_box()],
                                  expected_height=1.0,
                                  headroom_applies=False)
    assert report.score <= PASS_SCORE, report.to_dict()


def test_hand_subject_suggestions_no_longer_demand_whole_body_in_frame():
    """建议不得再要求"整身入画"（旧口径的修法方向错误）。"""
    report = evaluate_composition(
        [_body_box(), _hand_box()], primary="米迦尔:hand",
        expected_height=1.0, headroom_applies=False)
    joined = "；".join(report.suggestions)
    assert "整身" not in joined
    assert "收紧景别" not in joined
    assert "出画" not in joined


def test_hand_subject_provenance_is_anchored():
    """裁决 D1=A：无手部子网格时锚点+预设偏移，来源如实标注。"""
    box = _hand_box()
    assert box.provenance == "anchored"
    report = evaluate_composition(
        [_body_box(), box], primary="米迦尔:hand",
        expected_height=1.0, headroom_applies=False)
    assert report.score > PASS_SCORE


def test_primary_falls_back_to_visible_max_when_named_box_missing():
    """primary 指向不存在的盒（如道具未建）时必须回落旧主锚，不崩。"""
    report = evaluate_composition([_body_box(), _hand_box()],
                                  primary="不存在的盒",
                                  expected_height=1.0,
                                  headroom_applies=False)
    assert report.score > 0.0
